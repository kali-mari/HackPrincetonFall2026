#!/bin/sh
set -eu
if [ "${1:-}" = daphne ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput --clear
fi
exec "$@"
