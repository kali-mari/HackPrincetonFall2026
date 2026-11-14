"""Route smoke tests. SimpleTestCase forbids database access by the scaffolds."""

import json
import re
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings
from django.urls import resolve, reverse
from jsonschema import Draft202012Validator

from aac.http import MAX_JSON_BYTES
from aac.openapi import IDS, build_openapi


class EndpointScaffoldTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = build_openapi()
        cls.error_schema = cls.document["components"]["schemas"]["Error"]

    def setUp(self):
        # Ensure API writes do not accidentally depend on browser CSRF cookies.
        self.client = Client(enforce_csrf_checks=True)

    def routes(self):
        for path, methods in self.document["paths"].items():
            business = {
                method: op
                for method, op in methods.items()
                if op["x-implementation-status"] == "scaffolded"
            }
            if business:
                yield re.sub(r"\{[^}]+\}", IDS["patient"], path), business

    def test_every_documented_business_operation_is_routable(self):
        count = 0
        for path, methods in self.routes():
            self.assertEqual(resolve(path).namespace, "aac")
            for method, operation in methods.items():
                example = (
                    operation.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("example")
                )
                kwargs = (
                    {"data": json.dumps(example), "content_type": "application/json"}
                    if example is not None
                    else {}
                )
                with self.subTest(path=path, method=method):
                    response = self.client.generic(method.upper(), path, **kwargs)
                    self.assertEqual(response.status_code, 501)
                    self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertEqual(
                        response.json(),
                        operation["responses"]["501"]["content"]["application/json"][
                            "example"
                        ],
                    )
                    Draft202012Validator(self.error_schema).validate(response.json())
                count += 1
        self.assertEqual(count, 9)

    def test_methods_options_and_head(self):
        for path, methods in self.routes():
            with self.subTest(path=path):
                expected = {method.upper() for method in methods} | {"OPTIONS"}
                if "GET" in expected:
                    expected.add("HEAD")
                response = self.client.put(path, "{}", content_type="application/json")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.json()["error"]["code"], "method_not_allowed")
                self.assertEqual(set(response["Allow"].split(", ")), expected)
                options = self.client.options(path)
                self.assertEqual(options.status_code, 204)
                self.assertEqual(options.content, b"")
                self.assertEqual(set(options["Allow"].split(", ")), expected)
                head = self.client.head(path)
                self.assertEqual(head.status_code, 501 if "get" in methods else 405)
                self.assertEqual(head.content, b"")

    def test_invalid_json_transport_on_every_write_operation(self):
        invalid_bodies = (
            b"",
            b"{",
            b"[]",
            b"null",
            b'"text"',
            b"42",
            b"\xff",
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":1e9999}',
        )
        for path, methods in self.routes():
            for method in methods.keys() & {"post", "patch"}:
                for body in invalid_bodies:
                    with self.subTest(path=path, method=method, body=body):
                        response = self.client.generic(
                            method.upper(),
                            path,
                            data=body,
                            content_type="application/json",
                        )
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(
                            response.json()["error"]["code"], "invalid_request"
                        )
                        Draft202012Validator(self.error_schema).validate(
                            response.json()
                        )
                response = self.client.generic(
                    method.upper(), path, data="{}", content_type="text/plain"
                )
                self.assertEqual(response.status_code, 400)

    def test_body_limit_returns_json_error(self):
        response = self.client.post(
            "/api/learn/analyze",
            json.dumps({"text": "x" * MAX_JSON_BYTES}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_parser_recursion_returns_json_error(self):
        # The decoder's nesting limit varies by Python version; test the handler,
        # rather than assuming a particular nesting depth always raises.
        with patch("aac.http.json.loads", side_effect=RecursionError):
            response = self.client.post(
                "/api/learn/analyze", "{}", content_type="application/json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10)
    def test_django_body_limit_returns_json_not_html(self):
        response = self.client.post(
            "/api/learn/analyze", {"text": "long enough"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_schema_validation_is_not_misrepresented_as_implemented(self):
        # Syntactically valid objects reach the scaffold, even with missing fields.
        # Field/query and ownership checks belong to the later feature handlers.
        response = self.client.post(
            "/api/learn/analyze", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 501)
        response = self.client.get(
            f"/api/learn/patients/{IDS['patient']}/label-definitions?limit=999"
        )
        self.assertEqual(response.status_code, 501)

    def test_uuid_paths_and_no_trailing_slash(self):
        url = reverse("aac:patient-detail", kwargs={"id": IDS["patient"]})
        self.assertEqual(url, f"/api/profile/patients/{IDS['patient']}")
        self.assertEqual(
            self.client.get("/api/profile/patients/not-a-uuid").status_code, 404
        )
        self.assertEqual(self.client.get(url + "/").status_code, 404)
