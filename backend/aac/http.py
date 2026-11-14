"""Shared method/JSON transport helpers and explicit scaffold responses."""

import json
import math

from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, JsonResponse

from .validation import InvalidRequest

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


def check_method(request, methods):
    """Return OPTIONS/405 responses, or None when the view should continue."""
    allowed = list(methods)
    if "GET" in methods:
        allowed.append("HEAD")
    allowed.append("OPTIONS")
    allow = ", ".join(allowed)
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        response["Allow"] = allow
        return response

    if request.method not in allowed:
        response = error_response(
            "method_not_allowed", f"Allowed methods: {allow}.", 405
        )
        response["Allow"] = allow
        return response

    return None


def read_json_object(request):
    """Return parsed data for a feature view, or raise a safe InvalidRequest.

    This checks transport only, not required/unknown fields or relationships.
    A view must catch InvalidRequest from this and its field validators and use
    error_response('invalid_request', str(error), 400).
    """
    if request.content_type != "application/json":
        raise InvalidRequest("Use Content-Type: application/json.")
    try:
        body = request.body
    except RequestDataTooBig:
        raise InvalidRequest("JSON body exceeds the request limit.") from None
    if len(body) > MAX_JSON_BYTES:
        raise InvalidRequest("JSON body exceeds 64 KiB.")
    try:
        payload = json.loads(
            body.decode("utf-8"),
            parse_constant=reject_nonfinite,
            parse_float=finite_float,
        )
    except (ValueError, RecursionError):
        raise InvalidRequest("Body must be valid UTF-8 JSON.") from None
    if not isinstance(payload, dict):
        raise InvalidRequest("JSON body must be an object.")
    return payload


def scaffold_response(request, operations):
    """Check transport, then decline unimplemented behavior without side effects.

    operations maps HTTP methods to OpenAPI operation IDs. Scaffolds deliberately
    do not opt into field/query validation before their feature is implemented.
    """
    response = check_method(request, operations)
    if response is not None:
        return response
    method = "GET" if request.method == "HEAD" else request.method
    if method in ("POST", "PATCH"):
        try:
            read_json_object(request)
        except InvalidRequest as error:
            return error_response("invalid_request", str(error), 400)
    return error_response(
        "not_implemented",
        f"{operations[method]} is scaffolded; feature implementation is pending.",
        501,
    )
