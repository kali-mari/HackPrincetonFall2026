"""Small HTTP helpers for the endpoint scaffold, not feature validation."""

import json
import math

from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, JsonResponse

MAX_JSON_BYTES = 64 * 1024


def error_response(code, message, status):
    response = JsonResponse(
        {"error": {"code": code, "message": message}}, status=status
    )
    # 501 is cacheable by default; a scaffold response must not survive implementation.
    response["Cache-Control"] = "no-store"
    return response


def reject_nonfinite(value):
    raise ValueError("Non-finite numbers are not valid JSON.")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Number exceeds the finite float range.")
    return number


def scaffold_response(request, operations):
    """Check transport basics, then explicitly decline unimplemented behavior.

    operations maps HTTP methods to OpenAPI operation IDs. No field/schema,
    query, relationship, database or provider validation is performed yet.
    """
    allowed = list(operations)
    if "GET" in operations:
        allowed.append("HEAD")
    allowed.append("OPTIONS")
    allow = ", ".join(allowed)
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        response["Allow"] = allow
        return response

    method = "GET" if request.method == "HEAD" else request.method
    if request.method not in allowed:
        response = error_response(
            "method_not_allowed", f"Allowed methods: {allow}.", 405
        )
        response["Allow"] = allow
        return response

    if method in ("POST", "PATCH"):
        if request.content_type != "application/json":
            return error_response(
                "invalid_request", "Use Content-Type: application/json.", 400
            )
        try:
            body = request.body
            if len(body) > MAX_JSON_BYTES:
                return error_response(
                    "invalid_request", "JSON body exceeds 64 KiB.", 400
                )
            payload = json.loads(
                body.decode("utf-8"),
                parse_constant=reject_nonfinite,
                parse_float=finite_float,
            )
        except RequestDataTooBig:
            return error_response(
                "invalid_request", "JSON body exceeds the request limit.", 400
            )
        except (ValueError, RecursionError):
            return error_response(
                "invalid_request", "Body must be valid UTF-8 JSON.", 400
            )
        if not isinstance(payload, dict):
            return error_response(
                "invalid_request", "JSON body must be an object.", 400
            )

    return error_response(
        "not_implemented",
        f"{operations[method]} is scaffolded; feature implementation is pending.",
        501,
    )
