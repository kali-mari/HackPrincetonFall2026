"""Plain function views; unfinished AAC/learning features remain explicit 501s."""

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .http import check_method, error_response, read_json_object, scaffold_response
from .models import CaregiverPatient, Profile
from .profile_validation import PATIENT_FIELDS, validate_patient_setup
from .profiles import patient_cursor, profile_json, read_patient_cursor
from .validation import InvalidRequest, query_limit, validate_fields, validate_string, validate_uuid


@csrf_exempt
def caregivers(request):
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        payload = read_json_object(request)
        validate_fields(payload, allowed={'display_name'}, required={'display_name'})
        name = validate_string(payload['display_name'], 'display_name', max_length=80)
        caregiver = Profile.objects.create(role=Profile.Role.CAREGIVER, display_name=name)
        return JsonResponse(profile_json(caregiver), status=201)
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except ValidationError:
        return error_response('invalid_request', 'Invalid caregiver setup.', 400)
    except DatabaseError:
        return error_response('unavailable', 'Profile storage is unavailable.', 503)


@csrf_exempt
def patients(request):
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        payload = read_json_object(request)
        validate_fields(payload, allowed=PATIENT_FIELDS | {'caregiver_id'},
                        required=PATIENT_FIELDS | {'caregiver_id'})
        caregiver_id = validate_uuid(payload['caregiver_id'], 'caregiver_id')
        setup = validate_patient_setup({key: payload[key] for key in PATIENT_FIELDS})
        with transaction.atomic():
            caregiver = Profile.objects.get(pk=caregiver_id, role=Profile.Role.CAREGIVER)
            patient = Profile.objects.create(role=Profile.Role.PATIENT, **setup)
            CaregiverPatient.objects.create(caregiver=caregiver, patient=patient)
        return JsonResponse(profile_json(patient), status=201)
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('not_found', 'Caregiver not found.', 404)
    except ValidationError:
        return error_response('invalid_request', 'Invalid patient setup or caregiver link.', 400)
    except DatabaseError:
        return error_response('unavailable', 'Profile storage is unavailable.', 503)


@csrf_exempt
def caregiver_patients(request, id):
    response = check_method(request, ('GET',))
    if response is not None:
        return response
    try:
        validate_fields(request.GET, allowed={'limit', 'cursor'})
        limit = query_limit(request.GET)
        after = read_patient_cursor(request.GET, id)
        caregiver = Profile.objects.get(pk=id, role=Profile.Role.CAREGIVER)
        rows = Profile.objects.filter(role=Profile.Role.PATIENT, caregiver_links__caregiver=caregiver)
        if after is not None:
            rows = rows.filter(pk__gt=after)
        rows = list(rows.order_by('id')[:limit + 1])
        page = rows[:limit]
        cursor = patient_cursor(id, page[-1].pk) if len(rows) > limit else None
        return JsonResponse({'patients': [profile_json(row) for row in page], 'next_cursor': cursor})
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('not_found', 'Caregiver not found.', 404)
    except DatabaseError:
        return error_response('unavailable', 'Profile storage is unavailable.', 503)


@csrf_exempt
def patient_detail(request, id):
    response = check_method(request, ('GET', 'PATCH', 'DELETE'))
    if response is not None:
        return response
    try:
        setup = None
        if request.method == 'PATCH':
            setup = validate_patient_setup(read_json_object(request), partial=True)
        # Updates/deletion stay atomic as later patient-owned tables are added.
        with transaction.atomic():
            patient = Profile.objects.get(pk=id, role=Profile.Role.PATIENT)
            if request.method == 'DELETE':
                patient.delete()
                return HttpResponse(status=204)
            if setup is not None:
                for field, value in setup.items():
                    setattr(patient, field, value)
                patient.save()
            return JsonResponse(profile_json(patient))
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('not_found', 'Patient not found.', 404)
    except ValidationError:
        return error_response('invalid_request', 'Invalid patient setup.', 400)
    except DatabaseError:
        return error_response('unavailable', 'Profile storage is unavailable.', 503)


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
