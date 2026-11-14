"""Read-only documentation endpoints; no business behavior is stubbed here."""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .openapi import build_openapi


def method_error():
    response = JsonResponse(
        {"error": {"code": "method_not_allowed", "message": "Use GET or HEAD."}},
        status=405,
    )
    response["Allow"] = "GET, HEAD"
    return response


@csrf_exempt
def openapi_document(request):
    if request.method not in ("GET", "HEAD"):
        return method_error()
    return JsonResponse(build_openapi(), json_dumps_params={"indent": 2})


@csrf_exempt
def swagger_ui(request):
    if request.method not in ("GET", "HEAD"):
        return method_error()
    return render(request, "aac/swagger.html")
