"""Offer the Mac microphone to UNO Q over an ADB reverse tunnel.

Capture opens only while the UNO Q listener is connected. Audio is streamed as
16 kHz mono WAV through memory; no recording is saved. Bind loopback only.
"""

import argparse
import select
import shutil
import socket
import subprocess


def capture_command(ffmpeg, device):
    return [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-f', 'avfoundation', '-i', f':{device}', '-vn',
            '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
            '-f', 'wav', '-flush_packets', '1', 'pipe:1']


def stream(connection, command):
    """Stop capture on remote disconnect, even if microphone permission is pending."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    try:
        connection.settimeout(2)
        print('Microphone opened for UNO Q listening.', flush=True)
        while True:
            ready, _, _ = select.select([connection, process.stdout], [], [], 0.5)
            if connection in ready:
                if not connection.recv(1):
                    break
            if process.stdout in ready:
                chunk = process.stdout.read1(2048)
                if not chunk:
                    if process.wait() != 0:
                        print('Microphone capture failed. Check macOS microphone permission and device name.', flush=True)
                    break
                connection.sendall(chunk)
    except (ConnectionError, TimeoutError, OSError):
        pass  # stopping Listen mode closes the peer; never replay buffered audio
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()
        print('Microphone closed; audio discarded.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='MacBook Pro Microphone',
                        help='AVFoundation audio device name or index (ffmpeg -f avfoundation -list_devices true -i "")')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        parser.error('ffmpeg is required on the Mac.')
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', args.port))
        server.listen(1)
        print(f'Mic relay ready on 127.0.0.1:{args.port}; microphone is off until listening starts.', flush=True)
        try:
            while True:
                connection, _ = server.accept()
                with connection:
                    stream(connection, capture_command(ffmpeg, args.device))
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
