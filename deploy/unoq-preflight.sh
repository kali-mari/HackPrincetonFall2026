#!/bin/sh
# Read-only checks; does not install packages or change Arduino services.
set -eu
cd "$(dirname "$0")/.."
test "$(uname -s)" = Linux || { echo 'Run this on the UNO Q Linux host.' >&2; exit 1; }
test "$(uname -m)" = aarch64 || { echo 'Expected the UNO Q ARM64 host.' >&2; exit 1; }
docker version --format 'Docker server: {{.Server.Version}}'
docker compose version
if ! test -f /sys/fs/cgroup/system.slice/cpu.max; then
    echo 'CPU quota interface absent; use the default configuration without compose.cpu-limits.yaml.'
fi
test -f backend/.env || { echo 'Create backend/.env from backend/.env.example first.' >&2; exit 1; }
# Do not print resolved configuration: it may contain credentials.
docker compose -f compose.yaml -f compose.unoq.yaml --profile conversation config --quiet
df -h .
free -h
if test -d /dev/snd; then
    ls -ln /dev/snd
else
    echo 'No ALSA devices: core AAC works, microphone mode needs an audio device.'
fi
if test -S /var/run/arduino-router.sock; then
    echo 'Arduino router socket present; keep the UNO Q bridge on the host.'
else
    echo 'Arduino router socket absent; keyboard still works.'
fi
echo 'Check ports 5173/8000 for existing demo servers before starting Compose.'
ss -ltn
