"""Plain function views; unfinished AAC/learning features remain explicit 501s."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .http import check_method, error_response, read_json_object, scaffold_response
from .history import (
    Conflict, event_cursor, event_json, read_event_cursor, same_event, time_bucket, validate_event,
)
from .models import CaregiverPatient, CommunicationEvent, PredictionRecord, Profile
from .predictions import predict_phrases, recent_spoken, validate_prediction_request
from .profile_validation import PATIENT_FIELDS, validate_patient_setup
from .profiles import patient_cursor, profile_json, read_patient_cursor
from .validation import (
    InvalidRequest, query_limit, validate_fields, validate_string, validate_timestamp, validate_uuid,
)


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
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        payload = read_json_object(request)
        now, activity = validate_prediction_request(payload, {'patient_id', 'time', 'activity', 'recent'})
        patient_id = validate_uuid(payload['patient_id'], 'patient_id')
        patient = Profile.objects.get(pk=patient_id, role=Profile.Role.PATIENT)
        bucket = time_bucket(now, patient.timezone)
        try:
            events = recent_spoken(patient)
        except DatabaseError:
            events = []  # Unavailable history still yields six defaults.
        phrases, source = predict_phrases(events, activity, bucket, now)
        # Attribution needs a saved record, so a failed save is not a success.
        record = PredictionRecord.objects.create(
            patient=patient, activity=activity, time_bucket=bucket, phrases=phrases, source=source,
        )
        return JsonResponse({
            'prediction_id': str(record.pk), 'phrases': phrases, 'source': source, 'artifact_version': None,
        })
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('not_found', 'Patient not found.', 404)
    except DatabaseError:
        return error_response('unavailable', 'Prediction storage is unavailable.', 503)


def save_event(data):
    """Create a validated event, or return the identical stored retry (created=False)."""
    with transaction.atomic():
        existing = CommunicationEvent.objects.filter(pk=data['id']).first()
        if existing is not None:
            if not same_event(existing, data):
                raise Conflict('event_id was already used for a different event.')
            return existing, False
        patient = Profile.objects.get(pk=data['patient_id'], role=Profile.Role.PATIENT)
        if data['prediction_id'] is not None:
            prediction = PredictionRecord.objects.get(pk=data['prediction_id'], patient=patient)
            if prediction.phrases[data['candidate_index']] != data['text']:
                raise InvalidRequest('text does not match the predicted candidate.')
        utterance = CommunicationEvent.objects.filter(utterance_id=data['utterance_id'])
        if utterance.exclude(patient=patient).exists():
            raise Conflict('utterance_id belongs to a different patient.')
        if data['kind'] == 'spoken' and utterance.filter(kind='spoken').exists():
            raise Conflict('This utterance already has a spoken event.')
        event = CommunicationEvent.objects.create(
            time_bucket=time_bucket(data['occurred_at'], patient.timezone), **data,
        )
        return event, True


@csrf_exempt
def events(request):
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        data = validate_event(read_json_object(request))
        try:
            event, created = save_event(data)
        except IntegrityError:
            # A concurrent write won the race; answer as if it had arrived first.
            event = CommunicationEvent.objects.filter(pk=data['id']).first()
            if event is None or not same_event(event, data):
                raise Conflict('Event conflicts with a concurrent write.') from None
            created = False
        return JsonResponse({'event_id': str(event.pk)}, status=201 if created else 200)
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('not_found', 'Patient not found.', 404)
    except PredictionRecord.DoesNotExist:
        return error_response('not_found', 'Prediction not found for this patient.', 404)
    except Conflict as error:
        return error_response('conflict', str(error), 409)
    except DatabaseError:
        return error_response('unavailable', 'Event storage is unavailable.', 503)


@csrf_exempt
def patient_events(request, id):
    response = check_method(request, ('GET',))
    if response is not None:
        return response
    try:
        validate_fields(request.GET, allowed={'limit', 'cursor'})
        limit = query_limit(request.GET)
        after = read_event_cursor(request.GET, id)
        patient = Profile.objects.get(pk=id, role=Profile.Role.PATIENT)
        rows = CommunicationEvent.objects.filter(patient=patient)
        if after is not None:
            timestamp, event_id = after
            rows = rows.filter(Q(occurred_at__lt=timestamp) | Q(occurred_at=timestamp, id__lt=event_id))
        rows = list(rows.order_by('-occurred_at', '-id')[:limit + 1])
        page = rows[:limit]
        cursor = event_cursor(id, page[-1]) if len(rows) > limit else None
        return JsonResponse({'events': [event_json(row) for row in page], 'next_cursor': cursor})
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('not_found', 'Patient not found.', 404)
    except DatabaseError:
        return error_response('unavailable', 'Event storage is unavailable.', 503)


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
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        now, activity = validate_prediction_request(read_json_object(request), {'time', 'activity', 'recent'})
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    # The legacy contract has no error for missing setup or storage: fall back to defaults.
    try:
        patient = Profile.objects.get(pk=settings.LEGACY_DEMO_PATIENT_ID, role=Profile.Role.PATIENT)
        events, bucket = recent_spoken(patient), time_bucket(now, patient.timezone)
    except (Profile.DoesNotExist, DatabaseError):
        events, bucket = [], None
    phrases, _ = predict_phrases(events, activity, bucket, now)
    return JsonResponse({'phrases': phrases})


@csrf_exempt
def legacy_log(request):
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        payload = read_json_object(request)
        validate_fields(payload, allowed={'text', 'timestamp'}, required={'text', 'timestamp'})
        text = validate_string(payload['text'], 'text', max_length=500)
        occurred_at = validate_timestamp(payload['timestamp'], 'timestamp')
        patient = Profile.objects.get(pk=settings.LEGACY_DEMO_PATIENT_ID, role=Profile.Role.PATIENT)
        # No retry key in this contract: every call is a new utterance.
        CommunicationEvent.objects.create(
            id=uuid.uuid4(), utterance_id=uuid.uuid4(), patient=patient, kind='spoken', text=text,
            occurred_at=occurred_at, time_bucket=time_bucket(occurred_at, patient.timezone),
        )
        return JsonResponse({'ok': True})
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    except Profile.DoesNotExist:
        return error_response('unavailable', 'Demo patient is not set up; run seed_demo.', 503)
    except DatabaseError:
        return error_response('unavailable', 'Event storage is unavailable.', 503)
