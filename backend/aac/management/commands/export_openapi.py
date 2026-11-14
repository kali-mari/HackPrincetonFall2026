"""Export the same contract Swagger UI serves, without a running server."""

import json

from django.core.management.base import BaseCommand

from aac.openapi import build_openapi


class Command(BaseCommand):
    help = "Print the OpenAPI contract as JSON (redirect to a file if needed)."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(build_openapi(), indent=2))
