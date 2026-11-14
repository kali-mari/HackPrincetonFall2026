"""Schema/example checks, not claims that planned business routes work."""

from io import StringIO
import json
from pathlib import Path
import re

from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import Client, SimpleTestCase
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from aac.openapi import IDS, NOW, SIX, build_openapi, ref


class ContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = build_openapi()
        resource = Resource.from_contents(
            cls.document, default_specification=DRAFT202012
        )
        cls.registry = Registry().with_resource("urn:aac:contract", resource)

    def validator(self, schema):
        # Resolve component refs against the complete OpenAPI document, offline.
        return Draft202012Validator(
            self.absolute_refs(schema),
            registry=self.registry,
            format_checker=FormatChecker(),
        )

    def absolute_refs(self, value):
        if isinstance(value, dict):
            return {
                key: (
                    "urn:aac:contract" + item
                    if key == "$ref" and item.startswith("#")
                    else self.absolute_refs(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.absolute_refs(item) for item in value]
        return value

    def test_openapi_is_valid(self):
        validate(self.document)

    def test_all_examples_match_their_schemas(self):
        count = 0
        for path, methods in self.document["paths"].items():
            for method, operation in methods.items():
                contents = [operation.get("requestBody", {}).get("content", {})]
                contents += [
                    response.get("content", {})
                    for response in operation["responses"].values()
                ]
                for content in contents:
                    for media in content.values():
                        if "example" in media:
                            with self.subTest(
                                path=path, method=method, example=media["example"]
                            ):
                                self.validator(media["schema"]).validate(
                                    media["example"]
                                )
                            count += 1
        self.assertGreater(count, 70)

    def test_unique_operation_ids_and_path_parameters(self):
        ids = []
        for path, methods in self.document["paths"].items():
            expected = set(re.findall(r"\{([^}]+)\}", path))
            for operation in methods.values():
                ids.append(operation["operationId"])
                actual = {
                    p["name"]
                    for p in operation.get("parameters", [])
                    if p["in"] == "path" and p["required"]
                }
                self.assertEqual(expected, actual)
        self.assertEqual(len(ids), len(set(ids)))

    def test_business_operations_are_explicitly_scaffolded(self):
        for path, methods in self.document["paths"].items():
            for operation in methods.values():
                implemented = path.startswith('/api/profile/') or path in ("/api/docs", "/api/openapi.json")
                self.assertEqual(
                    operation["x-implementation-status"],
                    "implemented" if implemented else "scaffolded",
                )
                if implemented:
                    self.assertNotIn('501', operation['responses'])
                else:
                    self.assertTrue(operation["summary"].startswith("[SCAFFOLD]"))
                    self.assertIn("501", operation["responses"])
        self.assertFalse(any("conversation" in path for path in self.document["paths"]))

    def test_legacy_shapes_and_six_phrase_constraint(self):
        expected = {
            "LegacySpeakRequest": {"text"},
            "LegacyPredictRequest": {"time", "activity", "recent"},
            "LegacyLogRequest": {"text", "timestamp"},
            "LegacyPredictResponse": {"phrases"},
            "SpeakResponse": {"audio_url"},
        }
        for name, keys in expected.items():
            self.assertEqual(
                set(self.document["components"]["schemas"][name]["properties"]), keys
            )
        validator = self.validator(ref("LegacyPredictResponse"))
        self.assertTrue(validator.is_valid({"phrases": SIX}))
        for phrases in (SIX[:5], SIX + ["Extra"], [SIX[0]] * 6, [" "] + SIX[1:]):
            self.assertFalse(validator.is_valid({"phrases": phrases}))

    def test_event_variants_and_attribution(self):
        event = {
            "event_id": IDS["event"],
            "utterance_id": IDS["utterance"],
            "patient_id": IDS["patient"],
            "kind": "spoken",
            "text": SIX[0],
            "timestamp": NOW,
            "input_source": "keyboard",
        }
        validator = self.validator(ref("EventCreate"))
        self.assertTrue(validator.is_valid(event))
        invalid = [
            {**event, "kind": "feedback"},
            {**event, "prediction_id": IDS["prediction"]},
            {**event, "candidate_index": 0},
            {**event, "input_source": "touch"},
            {**event, "timestamp": "2026-11-14T12:00:00"},
            {**event, "event_id": "not-a-uuid"},
            {**event, "transcript": "must not be accepted"},
        ]
        for value in invalid:
            self.assertFalse(validator.is_valid(value), value)
        feedback = {
            **event,
            "kind": "feedback",
            "prediction_id": IDS["prediction"],
            "candidate_index": 0,
            "outcome": "accepted",
        }
        self.assertTrue(validator.is_valid(feedback))
        self.assertFalse(validator.is_valid({**feedback, "candidate_index": 6}))

    def test_review_actions_reject_ambiguous_payloads(self):
        base = {"caregiver_id": IDS["caregiver"], "revision": 1}
        definitions = self.validator(ref("DefinitionReview"))
        self.assertTrue(definitions.is_valid({**base, "action": "approve"}))
        self.assertFalse(definitions.is_valid({**base, "action": "edit"}))
        self.assertFalse(definitions.is_valid({**base, "action": "map_existing"}))
        self.assertFalse(
            definitions.is_valid({**base, "action": "approve", "origin": "caregiver"})
        )
        assignments = self.validator(ref("AssignmentReview"))
        self.assertFalse(assignments.is_valid({**base, "action": "correct"}))
        self.assertTrue(
            assignments.is_valid(
                {**base, "action": "correct", "definition_id": IDS["definition"]}
            )
        )

    def test_builds_are_independent_and_export_matches_http(self):
        changed = build_openapi()
        changed["components"]["schemas"]["Event"]["properties"]["event_id"][
            "format"
        ] = "wrong"
        changed["paths"]["/api/aac/patients/{id}/events"]["get"]["parameters"][0][
            "schema"
        ]["maximum"] = 999
        self.assertEqual(build_openapi(), self.document)
        output = StringIO()
        call_command("export_openapi", stdout=output)
        self.assertEqual(json.loads(output.getvalue()), self.document)
        response = self.client.get("/api/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.document)


class DocumentationTests(SimpleTestCase):
    def test_offline_swagger_page(self):
        response = self.client.get("/api/docs")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profiles are implemented")
        self.assertContains(response, "scaffolded, not feature-complete")
        self.assertContains(response, "/api/openapi.json")
        self.assertNotContains(response, "https://")
        for asset in ("swagger-ui.css", "swagger-ui-bundle.js"):
            self.assertIsNotNone(finders.find(f"aac/vendor/swagger-ui/{asset}"))
        script = Path(finders.find("aac/swagger-init.js")).read_text()
        self.assertIn("validatorUrl: null", script)
        self.assertIn(
            'supportedSubmitMethods: ["get", "post", "patch", "delete"]', script
        )
        self.assertIn("queryConfigEnabled: false", script)

    def test_head_and_unsupported_methods(self):
        for path in ("/api/docs", "/api/openapi.json"):
            self.assertEqual(self.client.head(path).status_code, 200)
            response = Client(enforce_csrf_checks=True).post(
                path, {}, content_type="application/json"
            )
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response["Allow"], "GET, HEAD")
            self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_scaffold_routes_are_not_fake_success_handlers(self):
        response = self.client.post(
            "/api/aac/predict", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["error"]["code"], "not_implemented")
