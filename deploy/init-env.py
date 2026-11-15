#!/usr/bin/env python3
"""Initialize deployment configuration without printing or replacing credentials."""

from pathlib import Path
import re
import secrets
import shutil


def initialize(root):
    backend_env = root / 'backend/.env'
    if not backend_env.exists():
        shutil.copyfile(root / 'backend/.env.example', backend_env)
    text = backend_env.read_text()
    key = re.search(r'^DJANGO_SECRET_KEY=(.*)$', text, re.MULTILINE)
    if key is None or key.group(1).strip().strip('"\'') in ('', 'django-insecure-local-development-only'):
        line = 'DJANGO_SECRET_KEY=' + secrets.token_urlsafe(48)
        if key:
            text = text[:key.start()] + line + text[key.end():]
        else:
            text = text.rstrip() + '\n' + line + '\n'
    text, count = re.subn(r'^DJANGO_DEBUG=.*$', 'DJANGO_DEBUG=false', text, flags=re.MULTILINE)
    if not count:
        text = text.rstrip() + '\nDJANGO_DEBUG=false\n'
    backend_env.write_text(text)
    backend_env.chmod(0o600)
    deployment_env = root / 'deploy/unoq.env'
    if not deployment_env.exists():
        shutil.copyfile(root / 'deploy/unoq.env.example', deployment_env)
    print('Deployment settings ready. Credentials were not displayed; existing provider settings were preserved.')


if __name__ == '__main__':
    initialize(Path(__file__).resolve().parents[1])
