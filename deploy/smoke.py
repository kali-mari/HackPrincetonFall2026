#!/usr/bin/env python3
"""Exercise a deployed gateway with synthetic profiles; never calls speech providers.

Run using a Python environment containing hardware/requirements.txt (websockets).
The temporary patient is deleted in finally, including on a failed assertion.
Uses the seeded demo caregiver by default; there is no public caregiver-delete API.
"""

import argparse
from datetime import datetime, timezone
import json
import re
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from websockets.sync.client import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:5173')
    parser.add_argument('--caregiver-id', default='11111111-1111-4111-8111-111111111111')
    parser.add_argument('--conversation', action='store_true',
                        help='Explicitly start capture. Use a file source for automated tests.')
    args = parser.parse_args()
    base = args.url.rstrip('/')

    def http(path, method='GET', body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(base + path, data=data, method=method,
                      headers={'Content-Type': 'application/json'} if data else {})
        with urlopen(req, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw

    assert b'<html' in http('/').lower()
    assert http('/api/openapi.json')['openapi'].startswith('3.')
    page = http('/api/docs').decode()
    assets = re.findall(r'(?:src|href)="(/static/[^\"]+)"', page)
    assert assets and all(http(asset) for asset in assets), 'Offline Swagger assets must be served.'
    host = urlsplit(base)
    ws_base = ('wss' if host.scheme == 'https' else 'ws') + '://' + host.netloc
    with connect(ws_base + '/ws/input/', origin=base) as receiver, \
            connect(ws_base + '/ws/input/') as sender:
        sender.send(json.dumps({'action': 'NEXT', 'source': 'button'}))
        assert json.loads(receiver.recv(timeout=5)) == {'action': 'NEXT', 'source': 'button'}
    patient = None
    try:
        patient = http('/api/profile/patients', 'POST', {
            'caregiver_id': args.caregiver_id, 'display_name': 'Synthetic container test',
            'timezone': 'UTC', 'language': 'en', 'preferences': {
                'scan_interval_ms': 1500, 'input_modes': ['button', 'keyboard'], 'default_activity': 'play'},
        })['id']
        result = http('/api/aac/predict', 'POST', {
            'patient_id': patient, 'time': datetime.now(timezone.utc).isoformat(),
            'activity': 'play', 'recent': [],
        })
        assert len(result['phrases']) == 6
        if args.conversation:
            with connect(ws_base + '/ws/conversation/', origin=base) as session:
                assert json.loads(session.recv(timeout=5)) == {'type': 'state', 'listening': False}
                session.send(json.dumps({'type': 'start', 'patient_id': patient}))
                message = json.loads(session.recv(timeout=40))
                assert message == {'type': 'state', 'listening': True}, message.get('type')
                # Actual model decode, without displaying or saving the transcript.
                message = json.loads(session.recv(timeout=45))
                assert message.get('type') == 'transcript' and message.get('text')
                message = json.loads(session.recv(timeout=20))
                assert message.get('type') == 'suggestions' and len(message['phrases']) in (0, 6)
                session.send(json.dumps({'type': 'stop'}))
                # A phrase already in flight can precede the stop acknowledgment.
                for _ in range(10):
                    if json.loads(session.recv(timeout=5)) == {'type': 'state', 'listening': False}:
                        break
                else:
                    raise AssertionError('Listening did not stop.')
        print('PASS: frontend, API, static assets, SQLite writes, six predictions, input WebSocket'
              + (', local transcription, conversation WebSocket and stop' if args.conversation else ''))
    finally:
        if patient:
            http('/api/profile/patients/' + patient, 'DELETE')


if __name__ == '__main__':
    main()
