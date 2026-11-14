"""Routable function views. Business features intentionally return JSON 501."""

from django.views.decorators.csrf import csrf_exempt

from .http import scaffold_response


@csrf_exempt
def caregivers(request):
    return scaffold_response(request, {"POST": "createCaregiver"})


@csrf_exempt
def patients(request):
    return scaffold_response(request, {"POST": "createPatient"})


@csrf_exempt
def caregiver_patients(request, id):
    return scaffold_response(request, {"GET": "listPatients"})


@csrf_exempt
def patient_detail(request, id):
    return scaffold_response(
        request,
        {
            "GET": "getPatient",
            "PATCH": "updatePatient",
            "DELETE": "deletePatient",
        },
    )


@csrf_exempt
def speak(request):
    return scaffold_response(request, {"POST": "speak"})


@csrf_exempt
def predict(request):
    return scaffold_response(request, {"POST": "predict"})


@csrf_exempt
def events(request):
    return scaffold_response(request, {"POST": "recordEvent"})


@csrf_exempt
def patient_events(request, id):
    return scaffold_response(request, {"GET": "listEvents"})


@csrf_exempt
def label_definitions(request, id):
    return scaffold_response(
        request, {"GET": "listDefinitions", "POST": "createDefinition"}
    )


@csrf_exempt
def definition_detail(request, id):
    return scaffold_response(request, {"PATCH": "reviewDefinition"})


@csrf_exempt
def event_labels(request, event_id):
    return scaffold_response(request, {"GET": "listEventLabels", "POST": "assignLabel"})


@csrf_exempt
def assignment_detail(request, id):
    return scaffold_response(request, {"PATCH": "reviewAssignment"})


@csrf_exempt
def analyze(request):
    return scaffold_response(request, {"POST": "analyze"})


@csrf_exempt
def learning_summary(request, id):
    return scaffold_response(request, {"GET": "learningSummary"})


@csrf_exempt
def activate(request):
    return scaffold_response(request, {"POST": "activateLearning"})


@csrf_exempt
def legacy_speak(request):
    return scaffold_response(request, {"POST": "legacySpeak"})


@csrf_exempt
def legacy_predict(request):
    return scaffold_response(request, {"POST": "legacyPredict"})


@csrf_exempt
def legacy_log(request):
    return scaffold_response(request, {"POST": "legacyLog"})
