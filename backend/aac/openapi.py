"""OpenAPI contracts with explicit per-operation implementation status.

Keep schemas explicit and export with `python manage.py export_openapi`.
Profiles, event history, predictions and speech are implemented; unfinished learning routes remain JSON 501 scaffolds.
"""

from copy import deepcopy


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def text(limit, **extra):
    return {"type": "string", "minLength": 1, "maxLength": limit, **extra}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def array(items, **extra):
    return {"type": "array", "items": items, **extra}


def obj(properties, required=(), **extra):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
        **extra,
    }


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


UUID = {"type": "string", "format": "uuid"}
TIME = {
    "type": "string",
    "format": "date-time",
    "description": "Timezone required; normalize to UTC.",
}
REVISION = {"type": "integer", "minimum": 1}
CONFIDENCE = nullable({"type": "number", "minimum": 0, "maximum": 1})
CATEGORY = enum("intent", "topic", "activity")
TEXT = text(500, pattern=r"\S")
PHRASES = array(TEXT, minItems=6, maxItems=6, uniqueItems=True)
PAGE_PARAMETERS = [
    {
        "name": "limit",
        "in": "query",
        "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    },
    {
        "name": "cursor",
        "in": "query",
        "schema": text(512),
        "description": "Opaque cursor; use unchanged with the same filters.",
    },
]
IDS = {
    "caregiver": "11111111-1111-4111-8111-111111111111",
    "patient": "22222222-2222-4222-8222-222222222222",
    "event": "33333333-3333-4333-8333-333333333333",
    "prediction": "44444444-4444-4444-8444-444444444444",
    "utterance": "55555555-5555-4555-8555-555555555555",
    "definition": "66666666-6666-4666-8666-666666666666",
    "analysis": "77777777-7777-4777-8777-777777777777",
    "artifact": "88888888-8888-4888-8888-888888888888",
}
NOW = "2026-11-14T12:00:00Z"
SIX = ["I want water", "More please", "I am hungry", "All done", "Help me", "Thank you"]
CONTEXT = {"time": TIME, "activity": text(100), "recent": array(TEXT, maxItems=20)}
EVENT_BASE = {
    "event_id": UUID,
    "utterance_id": UUID,
    "patient_id": UUID,
    "text": TEXT,
    "timestamp": TIME,
    "activity": text(100),
    "input_source": enum("button", "keyboard"),
    "prediction_id": UUID,
    "candidate_index": {"type": "integer", "minimum": 0, "maximum": 5},
}
EVENT_REQUIRED = (
    "event_id",
    "utterance_id",
    "patient_id",
    "text",
    "timestamp",
    "input_source",
    "kind",
)


def event_variant(kind):
    fields = {**EVENT_BASE, "kind": {"const": kind}}
    required = list(EVENT_REQUIRED)
    if kind == "feedback":
        fields["outcome"] = enum("accepted", "rejected")
        required += ["outcome", "prediction_id", "candidate_index"]
    return obj(
        fields,
        required,
        dependentRequired={
            "prediction_id": ["candidate_index"],
            "candidate_index": ["prediction_id"],
        },
    )


SCHEMAS = {
    "Error": obj(
        {"error": obj({"code": text(80), "message": text(300)}, ("code", "message"))},
        ("error",),
    ),
    "Preferences": obj(
        {
            "scan_interval_ms": {
                "type": "integer",
                "minimum": 300,
                "maximum": 10000,
                "default": 1500,
            },
            "input_modes": array(
                enum("button", "keyboard"), minItems=1, uniqueItems=True
            ),
            "default_activity": text(100),
            "voice_id": text(100),
        },
        ("scan_interval_ms", "input_modes", "default_activity"),
    ),
    "CaregiverCreate": obj({"display_name": text(80)}, ("display_name",)),
    "PatientCreate": obj(
        {
            "caregiver_id": UUID,
            "display_name": text(80),
            "timezone": text(
                100, description="Valid IANA timezone, e.g. America/New_York."
            ),
            "language": text(35, description="Supported language tag, initially en."),
            "preferences": ref("Preferences"),
        },
        ("caregiver_id", "display_name", "timezone", "language", "preferences"),
    ),
    "PatientPatch": obj(
        {
            "display_name": text(80),
            "timezone": text(100),
            "language": text(35),
            "preferences": ref("Preferences"),
        },
        minProperties=1,
        description="Preferences replace the complete preferences object when supplied.",
    ),
    "Caregiver": obj(
        {
            "id": UUID,
            "role": {"const": "caregiver"},
            "display_name": text(80),
            "created_at": TIME,
            "updated_at": TIME,
        },
        ("id", "role", "display_name", "created_at", "updated_at"),
    ),
    "Patient": obj(
        {
            "id": UUID,
            "role": {"const": "patient"},
            "display_name": text(80),
            "timezone": text(100),
            "language": text(35),
            "preferences": ref("Preferences"),
            "created_at": TIME,
            "updated_at": TIME,
        },
        (
            "id",
            "role",
            "display_name",
            "timezone",
            "language",
            "preferences",
            "created_at",
            "updated_at",
        ),
    ),
    "LegacySpeakRequest": obj({"text": TEXT}, ("text",)),
    "SpeakRequest": obj({"patient_id": UUID, "text": TEXT}, ("patient_id", "text")),
    "SpeakResponse": obj(
        {"audio_url": {"type": "string", "format": "uri"}}, ("audio_url",)
    ),
    "LegacyPredictRequest": obj(CONTEXT, ("time", "activity", "recent")),
    "PredictRequest": obj(
        {"patient_id": UUID, **CONTEXT}, ("patient_id", "time", "activity", "recent")
    ),
    "LegacyPredictResponse": obj({"phrases": PHRASES}, ("phrases",)),
    "PredictResponse": obj(
        {
            "prediction_id": UUID,
            "phrases": PHRASES,
            "source": enum("jev", "ai", "history", "default"),
            "artifact_version": nullable(REVISION),
        },
        ("prediction_id", "phrases", "source", "artifact_version"),
    ),
    "LegacyLogRequest": obj({"text": TEXT, "timestamp": TIME}, ("text", "timestamp")),
    "LegacyLogResponse": obj({"ok": {"const": True}}, ("ok",)),
    "EventCreate": {
        "oneOf": [event_variant(kind) for kind in ("selection", "spoken", "feedback")],
        "description": (
            "UUID event_id is the retry key; utterance_id links selection/playback/feedback for one intentional utterance. "
            "Both prediction_id and candidate_index must be supplied together, and text must match the returned candidate. "
            "For edited/manual text omit both. Only completed playback creates spoken. Displayed suggestions are not events."
        ),
    },
    "EventReceipt": obj({"event_id": UUID}, ("event_id",)),
    "Event": obj(
        {
            "event_id": UUID,
            "utterance_id": UUID,
            "patient_id": UUID,
            "kind": enum("selection", "spoken", "feedback"),
            "text": TEXT,
            "timestamp": TIME,
            "received_at": TIME,
            "activity": nullable(text(100)),
            "input_source": nullable(enum("button", "keyboard")),
            "prediction_id": nullable(UUID),
            "candidate_index": nullable(
                {"type": "integer", "minimum": 0, "maximum": 5}
            ),
            "outcome": nullable(enum("accepted", "rejected")),
        },
        (
            "event_id",
            "utterance_id",
            "patient_id",
            "kind",
            "text",
            "timestamp",
            "received_at",
            "input_source",
            "prediction_id",
            "candidate_index",
            "outcome",
            "activity",
        ),
    ),
    "DefinitionCreate": obj(
        {
            "caregiver_id": UUID,
            "category": CATEGORY,
            "display_name": text(80),
            "description": text(300),
        },
        ("caregiver_id", "category", "display_name", "description"),
    ),
    "LabelDefinition": obj(
        {
            "id": UUID,
            "patient_id": nullable(UUID),
            "category": CATEGORY,
            "code": text(50, pattern="^[a-z][a-z0-9_]*$"),
            "display_name": text(80),
            "description": text(300),
            "origin": enum("system", "caregiver", "ai"),
            "status": enum("proposed", "active", "rejected", "archived"),
            "revision": REVISION,
            "vocabulary_revision": REVISION,
            "analysis_id": nullable(UUID),
            "created_by": nullable(UUID),
            "reviewed_by": nullable(UUID),
            "canonical_definition_id": nullable(UUID),
            "supporting_event_ids": array(UUID, maxItems=1000, uniqueItems=True),
            "created_at": TIME,
            "updated_at": TIME,
        },
        (
            "id",
            "patient_id",
            "category",
            "code",
            "display_name",
            "description",
            "origin",
            "status",
            "revision",
            "vocabulary_revision",
            "analysis_id",
            "created_by",
            "reviewed_by",
            "canonical_definition_id",
            "supporting_event_ids",
            "created_at",
            "updated_at",
        ),
    ),
    "AssignmentCreate": obj(
        {"caregiver_id": UUID, "definition_id": UUID}, ("caregiver_id", "definition_id")
    ),
    "EventLabel": obj(
        {
            "id": UUID,
            "event_id": UUID,
            "definition_id": UUID,
            "origin": enum("context", "rule", "caregiver", "ai"),
            "status": enum("proposed", "confirmed", "rejected", "superseded"),
            "confidence": CONFIDENCE,
            "revision": REVISION,
            "analysis_id": nullable(UUID),
            "reviewed_by": nullable(UUID),
            "supersedes_id": nullable(UUID),
            "provider_version": nullable(text(100)),
            "created_at": TIME,
            "updated_at": TIME,
        },
        (
            "id",
            "event_id",
            "definition_id",
            "origin",
            "status",
            "confidence",
            "revision",
            "analysis_id",
            "reviewed_by",
            "supersedes_id",
            "provider_version",
            "created_at",
            "updated_at",
        ),
    ),
    "AnalysisRequest": obj(
        {
            "patient_id": UUID,
            "requested_by": UUID,
            "from": TIME,
            "to": TIME,
        },
        ("patient_id", "requested_by", "from", "to"),
        description="from inclusive, to exclusive; ordered window of at most 30 days, latest 1,000 events. Requires explicit external-analysis consent outside this request; never includes Conversation Mode data.",
    ),
    "AnalysisResponse": obj(
        {
            "analysis_id": UUID,
            "patient_id": UUID,
            "status": {"const": "completed"},
            "from": TIME,
            "to": TIME,
            "event_cutoff": nullable(TIME),
            "event_count": {"type": "integer", "minimum": 0, "maximum": 1000},
            "truncated": {"type": "boolean"},
            "proposed_definitions": array(ref("LabelDefinition"), maxItems=10),
            "proposed_assignments": array(ref("EventLabel"), maxItems=3000),
            "candidate_artifact_version": nullable(REVISION),
        },
        (
            "analysis_id",
            "patient_id",
            "status",
            "from",
            "to",
            "event_cutoff",
            "event_count",
            "truncated",
            "proposed_definitions",
            "proposed_assignments",
            "candidate_artifact_version",
        ),
    ),
    "LearningSummary": obj(
        {
            "patient_id": UUID,
            "latest_analysis_id": nullable(UUID),
            "latest_analysis_status": nullable(enum("completed", "failed")),
            "last_analyzed_event_cutoff": nullable(TIME),
            "active_artifact_version": nullable(REVISION),
            "vocabulary_revision": REVISION,
            "definition_counts": obj(
                {
                    k: {"type": "integer", "minimum": 0}
                    for k in ("proposed", "active", "rejected", "archived")
                },
                ("proposed", "active", "rejected", "archived"),
            ),
            "assignment_counts": obj(
                {
                    k: {"type": "integer", "minimum": 0}
                    for k in ("proposed", "confirmed", "rejected", "superseded")
                },
                ("proposed", "confirmed", "rejected", "superseded"),
            ),
        },
        (
            "patient_id",
            "latest_analysis_id",
            "latest_analysis_status",
            "last_analyzed_event_cutoff",
            "active_artifact_version",
            "vocabulary_revision",
            "definition_counts",
            "assignment_counts",
        ),
    ),
    "ActivateRequest": obj(
        {
            "patient_id": UUID,
            "caregiver_id": UUID,
            "artifact_version": REVISION,
            "expected_active_version": nullable(REVISION),
            "vocabulary_revision": REVISION,
        },
        (
            "patient_id",
            "caregiver_id",
            "artifact_version",
            "expected_active_version",
            "vocabulary_revision",
        ),
    ),
    "ActivateResponse": obj(
        {
            "patient_id": UUID,
            "active_artifact_version": REVISION,
            "vocabulary_revision": REVISION,
        },
        ("patient_id", "active_artifact_version", "vocabulary_revision"),
    ),
    "InputMessage": obj(
        {
            "action": enum("PREV", "NEXT", "SELECT", "DELETE", "SPEAK"),
            "source": enum("button", "touch", "voice"),
        },
        ("action", "source"),
        description="Switch input from hardware/bridge.py. Buttons send PREV/NEXT/SELECT/DELETE/SPEAK with source button; the vocal switch and legacy touch always send SELECT. Keyboard is handled locally in the frontend, not added to this protocol.",
    ),
}

# Review actions are disjoint objects so invalid field combinations fail validation.
review_fields = {"caregiver_id": UUID, "revision": REVISION}
definition_actions = []
for action in ("edit", "approve", "reject", "archive", "map_existing"):
    fields = {**review_fields, "action": {"const": action}}
    required = ["caregiver_id", "revision", "action"]
    if action in ("edit", "approve"):
        fields.update(display_name=text(80), description=text(300))
    if action == "edit":
        definition_actions.append(
            obj(
                fields,
                required,
                anyOf=[{"required": ["display_name"]}, {"required": ["description"]}],
            )
        )
        continue
    if action == "map_existing":
        fields["definition_id"] = UUID
        required.append("definition_id")
    definition_actions.append(obj(fields, required))
SCHEMAS["DefinitionReview"] = {"oneOf": definition_actions}
SCHEMAS["AssignmentReview"] = {
    "oneOf": [
        obj(
            {
                **review_fields,
                "action": {"const": action},
                **({"definition_id": UUID} if action == "correct" else {}),
            },
            ["caregiver_id", "revision", "action"]
            + (["definition_id"] if action == "correct" else []),
        )
        for action in ("confirm", "reject", "correct")
    ]
}
for name, key, item in (
    ("PatientPage", "patients", "Patient"),
    ("EventPage", "events", "Event"),
    ("DefinitionPage", "definitions", "LabelDefinition"),
):
    SCHEMAS[name] = obj(
        {key: array(ref(item), maxItems=100), "next_cursor": nullable(text(512))},
        (key, "next_cursor"),
    )
SCHEMAS["AssignmentList"] = obj({"labels": array(ref("EventLabel"))}, ("labels",))


def response(schema, description="Success", example=None):
    result = {"description": description}
    if schema:
        media = {"schema": ref(schema)}
        if example is not None:
            media["example"] = example
        result["content"] = {"application/json": media}
    return result


def operation(
    operation_id,
    tag,
    summary,
    *,
    request=None,
    result=None,
    status=200,
    description="",
    request_example=None,
    response_example=None,
    parameters=(),
    errors=(400, 404, 405),
    extra_responses=None,
    implemented=False,
):
    responses = {str(status): response(result, "Success", response_example)}
    error_names = {
        400: "Invalid JSON, field value, limit, or relationship",
        404: "Record not found in allowed scope",
        405: "Method not allowed",
        409: "Duplicate, stale revision, or invalid state transition",
        503: "Required dependency unavailable; no fabricated success",
    }
    for code in errors:
        responses[str(code)] = response(
            "Error",
            error_names[code],
            {
                "error": {
                    "code": {
                        400: "invalid_request",
                        404: "not_found",
                        405: "method_not_allowed",
                        409: "conflict",
                        503: "unavailable",
                    }[code],
                    "message": error_names[code],
                }
            },
        )
    responses.update(extra_responses or {})
    if not implemented:
        responses["501"] = response(
            "Error",
            "Route scaffold exists; feature not implemented; no side effects",
            {
                "error": {
                    "code": "not_implemented",
                    "message": f"{operation_id} is scaffolded; feature implementation is pending.",
                }
            },
        )
    state = "implemented" if implemented else "scaffolded"
    result = {
        "operationId": operation_id,
        "tags": [tag],
        "summary": summary if implemented else f"[SCAFFOLD] {summary}",
        "description": (
            ""
            if implemented
            else "Route is wired but feature behavior is not implemented: returns JSON 501, without writes or provider calls. Transport checks: 400 for invalid/non-object/non-UTF-8 JSON, non-JSON Content-Type or body over 64 KiB; 405 with Allow for unsupported methods. OPTIONS returns 204 with Allow; HEAD follows GET without a body. Field/query/relationship validation and success responses below are target contracts, not implemented behavior.\n\n"
        )
        + description,
        "x-implementation-status": state,
        "responses": responses,
    }
    if parameters:
        result["parameters"] = list(parameters)
    if request:
        media = {"schema": ref(request)}
        if request_example is not None:
            media["example"] = request_example
        result["requestBody"] = {
            "required": True,
            "content": {"application/json": media},
        }
    return result


def build_openapi():
    paths = {}

    def add(path, method, operation_id, tag, summary, **kwargs):
        paths.setdefault(path, {})[method] = operation(
            operation_id, tag, summary, **kwargs
        )
        for part in path.split("/"):
            if part.startswith("{"):
                paths[path][method].setdefault("parameters", []).append(
                    {
                        "name": part[1:-1],
                        "in": "path",
                        "required": True,
                        "schema": deepcopy(UUID),
                    }
                )

    caregiver = {
        "id": IDS["caregiver"],
        "role": "caregiver",
        "display_name": "Demo caregiver",
        "created_at": NOW,
        "updated_at": NOW,
    }
    patient_create = {
        "caregiver_id": IDS["caregiver"],
        "display_name": "Demo patient",
        "timezone": "America/New_York",
        "language": "en",
        "preferences": {
            "scan_interval_ms": 1500,
            "input_modes": ["button", "keyboard"],
            "default_activity": "play",
        },
    }
    patient = {k: v for k, v in patient_create.items() if k != "caregiver_id"}
    patient.update(id=IDS["patient"], role="patient", created_at=NOW, updated_at=NOW)
    add(
        "/api/profile/caregivers",
        "post",
        "createCaregiver",
        "profile",
        "Create caregiver",
        implemented=True,
        request="CaregiverCreate",
        result="Caregiver",
        status=201,
        errors=(400, 405, 503),
        description="Persist a caregiver in SQLite. Only display_name is writable; no authentication is provided.",
        request_example={"display_name": "Demo caregiver"},
        response_example=caregiver,
    )
    add(
        "/api/profile/patients",
        "post",
        "createPatient",
        "profile",
        "Create patient and caregiver link",
        implemented=True,
        errors=(400, 404, 405, 503),
        request="PatientCreate",
        result="Patient",
        status=201,
        request_example=patient_create,
        response_example=patient,
        description="Caregiver must exist with caregiver role (otherwise 404). Patient and relationship are created atomically in SQLite. Validate IANA timezone, language en and complete preferences. IDs supplied by clients are not authentication.",
    )
    add(
        "/api/profile/caregivers/{id}/patients",
        "get",
        "listPatients",
        "profile",
        "List linked patients",
        implemented=True,
        errors=(400, 404, 405, 503),
        description="Stable ascending UUID keyset pagination. Signed cursors are bound to caregiver and order, not page size; malformed, repeated or mismatched cursors/limits and unknown query fields return 400. Results reflect live data, not a snapshot.",
        result="PatientPage",
        parameters=PAGE_PARAMETERS,
        response_example={"patients": [patient], "next_cursor": None},
    )
    add(
        "/api/profile/patients/{id}",
        "get",
        "getPatient",
        "profile",
        "Read patient setup",
        implemented=True,
        errors=(400, 404, 405, 503),
        description="Read persisted patient setup. A caregiver ID or missing patient returns 404.",
        result="Patient",
        response_example=patient,
    )
    add(
        "/api/profile/patients/{id}",
        "patch",
        "updatePatient",
        "profile",
        "Update patient setup",
        implemented=True,
        errors=(400, 404, 405, 503),
        description="Validate mutable setup fields only; IDs/role cannot change. Supplied preferences replace the complete object. Only language en is currently supported.",
        request="PatientPatch",
        result="Patient",
        request_example={"preferences": patient["preferences"]},
        response_example=patient,
    )
    add(
        "/api/profile/patients/{id}",
        "delete",
        "deletePatient",
        "profile",
        "Delete patient and owned data",
        implemented=True,
        errors=(400, 404, 405, 503),
        status=204,
        description="Atomically delete patient and caregiver links, preserving caregivers and other patients. Also deletes the patient's communication events and prediction records. Later patient-owned tables must cascade and extend deletion tests as implemented; labels and artifacts are not implemented yet. Manual demo reset/cleanup is sufficient for synthetic hackathon data.",
    )

    predict_request = {"time": NOW, "activity": "lunch", "recent": ["I want"]}
    speech_description = "Text-to-speech, not microphone input. Generate MP3 audio with the configured provider (SPEECH_PROVIDER, currently ElevenLabs) and return an absolute playable URL under /media/audio/. Identical provider/model/voice/text may reuse cached audio. When GOOGLE_HOME_HOST is configured, also casts in the background; casting failure never changes the response. Does not record playback. Client records spoken only on completion; cancellation/failure creates no spoken event. 503 when the provider is unconfigured or fails, or audio cannot be stored; never a fake URL."
    prediction_description = "Return six nonempty phrases, unique after trim/case-fold. No automatic selection/speech. AI wait over two seconds, failure or invalid output uses history/default fallback (200). Rank confirmed spoken history with weight 0.5 ** (age_days / 7); clamp negative age to zero. Count each utterance once; selections, suggestions and passive conversation topics are not positive evidence. Match activity/time bucket first, then fill with broader history/defaults. No prediction expiry during the hackathon."
    add(
        "/api/speak",
        "post",
        "legacySpeak",
        "legacy",
        "Generate speech",
        request="LegacySpeakRequest",
        result="SpeakResponse",
        errors=(400, 405, 503),
        implemented=True,
        description=speech_description + " Uses the fixed demo patient's preferences.voice_id when that patient exists, otherwise SPEECH_VOICE_ID.",
        request_example={"text": SIX[0]},
        response_example={"audio_url": "http://localhost:8000/media/audio/demo.mp3"},
    )
    add(
        "/api/predict",
        "post",
        "legacyPredict",
        "legacy",
        "Predict six phrases",
        request="LegacyPredictRequest",
        result="LegacyPredictResponse",
        errors=(400, 405),
        implemented=True,
        description=prediction_description
        + " Fixed configured demo patient; legacy shape is unchanged. Saves no prediction record (no ID to attribute). If the demo patient is missing or storage is unavailable, returns six defaults with 200.",
        request_example=predict_request,
        response_example={"phrases": SIX},
    )
    add(
        "/api/log",
        "post",
        "legacyLog",
        "legacy",
        "Log confirmed speech",
        request="LegacyLogRequest",
        result="LegacyLogResponse",
        errors=(400, 405, 503),
        implemented=True,
        description="Preserve request shape; success shape is now specified as 200 {ok:true}. Saves a spoken event in SQLite for the fixed LEGACY_DEMO_PATIENT_ID patient, with new server-generated event/utterance IDs, null activity and null input_source. No retry key: blind retries duplicate speech history. 503 if storage is unavailable or the demo patient has not been created with seed_demo.",
        request_example={"text": SIX[0], "timestamp": NOW},
        response_example={"ok": True},
    )
    add(
        "/api/aac/speak",
        "post",
        "speak",
        "aac",
        "Generate patient speech",
        request="SpeakRequest",
        result="SpeakResponse",
        errors=(400, 404, 405, 503),
        implemented=True,
        description=speech_description + " Uses the patient's preferences.voice_id when set, otherwise SPEECH_VOICE_ID. Unknown or caregiver patient returns 404.",
        request_example={"patient_id": IDS["patient"], "text": SIX[0]},
        response_example={"audio_url": "http://localhost:8000/media/audio/demo.mp3"},
    )
    add(
        "/api/aac/predict",
        "post",
        "predict",
        "aac",
        "Predict patient phrases",
        request="PredictRequest",
        result="PredictResponse",
        errors=(400, 404, 405, 503),
        implemented=True,
        description=prediction_description
        + " Saves a prediction record (activity, time bucket, phrases, source) for event attribution; recent is validated but never stored. Unreadable history falls back to defaults; 503 only if the record cannot be saved. Unknown or caregiver patient returns 404.",
        request_example={"patient_id": IDS["patient"], **predict_request},
        response_example={
            "prediction_id": IDS["prediction"],
            "phrases": SIX,
            "source": "history",
            "artifact_version": None,
        },
    )
    event_request = {
        "event_id": IDS["event"],
        "utterance_id": IDS["utterance"],
        "patient_id": IDS["patient"],
        "kind": "spoken",
        "text": SIX[0],
        "timestamp": NOW,
        "activity": "lunch",
        "input_source": "button",
        "prediction_id": IDS["prediction"],
        "candidate_index": 0,
    }
    add(
        "/api/aac/events",
        "post",
        "recordEvent",
        "aac",
        "Save explicit patient action",
        request="EventCreate",
        result="EventReceipt",
        status=201,
        errors=(400, 404, 405, 409, 503),
        extra_responses={
            "200": response(
                "EventReceipt",
                "Identical retry; no duplicate",
                {"event_id": IDS["event"]},
            )
        },
        implemented=True,
        description="event_id is globally unique; identical normalized retries return 200, changed payload returns 409. Unknown patient, or a prediction_id not saved for this patient, returns 404; text that differs from the referenced candidate returns 400. Reusing an utterance_id for another patient returns 409. time_bucket is computed from the patient's timezone at event time. Same utterance_id links selection, spoken and feedback for one patient; intentional repeated speech uses new utterance/event IDs. At most one spoken event per utterance (409 otherwise). For prediction attribution, text/index must match the same patient's saved prediction. Feedback always identifies a candidate. No raw transcripts accepted.",
        request_example=event_request,
        response_example={"event_id": IDS["event"]},
    )
    event_result = {**event_request, "received_at": NOW, "outcome": None}
    add(
        "/api/aac/patients/{id}/events",
        "get",
        "listEvents",
        "aac",
        "Read patient history",
        result="EventPage",
        parameters=PAGE_PARAMETERS,
        errors=(400, 404, 405, 503),
        implemented=True,
        description="Newest first by (timestamp,event_id); signed cursor is bound to patient and sort order. Unknown or caregiver ID returns 404. input_source is null only for legacy /api/log entries.",
        response_example={"events": [event_result], "next_cursor": None},
    )

    definition = {
        "id": IDS["definition"],
        "patient_id": IDS["patient"],
        "category": "topic",
        "code": "quiet_space",
        "display_name": "Quiet space",
        "description": "Requests for a quieter place",
        "origin": "caregiver",
        "status": "active",
        "revision": 1,
        "vocabulary_revision": 1,
        "analysis_id": None,
        "created_by": IDS["caregiver"],
        "reviewed_by": IDS["caregiver"],
        "canonical_definition_id": None,
        "supporting_event_ids": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    assignment = {
        "id": IDS["event"],
        "event_id": IDS["event"],
        "definition_id": IDS["definition"],
        "origin": "caregiver",
        "status": "confirmed",
        "confidence": None,
        "revision": 1,
        "analysis_id": None,
        "reviewed_by": IDS["caregiver"],
        "supersedes_id": None,
        "provider_version": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    label_rules = "Fixed categories: intent/topic/activity. Global seeds + this patient's custom values only. Single effective intent/activity; multiple topics; unknown excludes known values in its category. Effective = confirmed assignment + active definition. AI definitions and assignments require separate review. Caregiver corrections take precedence. Never infer diagnoses."
    add(
        "/api/learn/patients/{id}/label-definitions",
        "get",
        "listDefinitions",
        "learn",
        "List available definitions",
        result="DefinitionPage",
        parameters=[
            *PAGE_PARAMETERS,
            {
                "name": "status",
                "in": "query",
                "schema": {
                    **enum("proposed", "active", "rejected", "archived"),
                    "default": "active",
                },
            },
        ],
        description=label_rules,
        response_example={"definitions": [definition], "next_cursor": None},
    )
    add(
        "/api/learn/patients/{id}/label-definitions",
        "post",
        "createDefinition",
        "learn",
        "Create caregiver label definition",
        request="DefinitionCreate",
        result="LabelDefinition",
        status=201,
        errors=(400, 404, 405, 409),
        description=label_rules
        + " Caregiver must be linked to patient. Server normalizes immutable code; duplicate scoped/global-shadowing codes return 409. Created active; no AI required.",
        request_example={
            "caregiver_id": IDS["caregiver"],
            "category": "topic",
            "display_name": "Quiet space",
            "description": "Requests for a quieter place",
        },
        response_example=definition,
    )
    add(
        "/api/learn/label-definitions/{id}",
        "patch",
        "reviewDefinition",
        "learn",
        "Edit or review a custom definition",
        request="DefinitionReview",
        result="LabelDefinition",
        errors=(400, 404, 405, 409),
        description="System definitions are read-only. edit changes display name/description only. approve/reject/map_existing require proposed; archive requires active. map_existing requires active same-category allowed-scope target, rejects proposal with canonical_definition_id and retargets pending assignments without confirming. AI approval may edit display name/description, never code/category/scope. Stale revision returns 409; increment revision and invalidate affected configurations. Definition approval does not approve assignments.",
        request_example={
            "caregiver_id": IDS["caregiver"],
            "revision": 1,
            "action": "archive",
        },
        response_example={**definition, "status": "archived", "revision": 2},
    )
    add(
        "/api/learn/events/{event_id}/labels",
        "post",
        "assignLabel",
        "learn",
        "Assign an active label",
        request="AssignmentCreate",
        result="EventLabel",
        status=201,
        errors=(400, 404, 405, 409),
        extra_responses={
            "200": response("EventLabel", "Assignment already effective", assignment)
        },
        description=label_rules
        + " Linked caregiver and same-patient event/definition required; replaces conflicting effective single-value assignment transactionally, preserving superseded history.",
        request_example={
            "caregiver_id": IDS["caregiver"],
            "definition_id": IDS["definition"],
        },
        response_example=assignment,
    )
    add(
        "/api/learn/events/{event_id}/labels",
        "get",
        "listEventLabels",
        "learn",
        "Read assignment review history",
        result="AssignmentList",
        description="Includes proposed, confirmed, rejected and superseded assignments for this event.",
        response_example={"labels": [assignment]},
    )
    add(
        "/api/learn/labels/{id}",
        "patch",
        "reviewAssignment",
        "learn",
        "Review event-label assignment",
        request="AssignmentReview",
        result="EventLabel",
        errors=(400, 404, 405, 409),
        description="confirm/reject operate on proposed assignments. correct supersedes a proposed/confirmed assignment and returns a new confirmed assignment using replacement definition_id. Active definition, same patient and linked caregiver required. Expected revision prevents stale edits. AI cannot approve itself.",
        request_example={
            "caregiver_id": IDS["caregiver"],
            "revision": 1,
            "action": "confirm",
        },
        response_example={**assignment, "revision": 2},
    )
    add(
        "/api/learn/analyze",
        "post",
        "analyze",
        "learn",
        "Analyze bounded observed history",
        request="AnalysisRequest",
        result="AnalysisResponse",
        errors=(400, 404, 405, 503),
        description="Synchronous bounded analysis with configured deadline; no background queue/202 response. At most 30 days/latest 1,000 events. Reuse vocabulary, propose at most 10 definitions and 3 assignments per event. Use only observed ordinary events, never Conversation Mode tables/context. Provider failure leaves effective labels and active configuration unchanged. Empty/no useful history returns empty proposals and null candidate. Candidate configuration contains only effective approved labels; proposals remain outside it. No automated agent framework required.",
        request_example={
            "patient_id": IDS["patient"],
            "requested_by": IDS["caregiver"],
            "from": "2026-11-07T00:00:00Z",
            "to": NOW,
        },
        response_example={
            "analysis_id": IDS["analysis"],
            "patient_id": IDS["patient"],
            "status": "completed",
            "from": "2026-11-07T00:00:00Z",
            "to": NOW,
            "event_cutoff": None,
            "event_count": 0,
            "truncated": False,
            "proposed_definitions": [],
            "proposed_assignments": [],
            "candidate_artifact_version": None,
        },
    )
    add(
        "/api/learn/patients/{id}/summary",
        "get",
        "learningSummary",
        "learn",
        "Read learning summary",
        result="LearningSummary",
        response_example={
            "patient_id": IDS["patient"],
            "latest_analysis_id": None,
            "latest_analysis_status": None,
            "last_analyzed_event_cutoff": None,
            "active_artifact_version": None,
            "vocabulary_revision": 1,
            "definition_counts": {
                "proposed": 0,
                "active": 21,
                "rejected": 0,
                "archived": 0,
            },
            "assignment_counts": {
                "proposed": 0,
                "confirmed": 0,
                "rejected": 0,
                "superseded": 0,
            },
        },
    )
    add(
        "/api/learn/activate",
        "post",
        "activateLearning",
        "learn",
        "Activate validated configuration",
        request="ActivateRequest",
        result="ActivateResponse",
        errors=(400, 404, 405, 409),
        description="Atomically activate the patient's validated candidate matching expected active version (null if none) and current vocabulary revision. Reject stale or invalid candidate with 409. Not model training; no unreviewed AI labels in active payload.",
        request_example={
            "patient_id": IDS["patient"],
            "caregiver_id": IDS["caregiver"],
            "artifact_version": 1,
            "expected_active_version": None,
            "vocabulary_revision": 1,
        },
        response_example={
            "patient_id": IDS["patient"],
            "active_artifact_version": 1,
            "vocabulary_revision": 1,
        },
    )
    add(
        "/api/openapi.json",
        "get",
        "getOpenApi",
        "documentation",
        "Read this OpenAPI document",
        implemented=True,
        errors=(405,),
        description="Implemented documentation endpoint; profiles, event history, /api/log, predictions and speech are implemented and learning routes remain scaffolded (501).",
    )
    paths["/api/openapi.json"]["get"]["responses"]["200"] = {
        "description": "OpenAPI 3.1 JSON document",
        "content": {"application/json": {"schema": {"type": "object"}}},
    }
    add(
        "/api/docs",
        "get",
        "swaggerDocs",
        "documentation",
        "Open offline Swagger UI",
        implemented=True,
        errors=(405,),
    )
    paths["/api/docs"]["get"]["responses"]["200"] = {
        "description": "Swagger UI with vendored assets; Try it out executes implemented operations and remaining scaffolds",
        "content": {"text/html": {"schema": {"type": "string"}}},
    }
    return deepcopy(
        {
            "openapi": "3.1.0",
            "info": {
                "title": "Smart AAC Board API",
                "version": "0.1.0",
                "description": "Contract-first local demo API. Documentation, six profile operations, event recording/history, legacy /api/log, deterministic predictions and speech (new and legacy) are implemented with SQLite persistence and field/relationship validation. Remaining learning routes marked SCAFFOLD return JSON 501 until implemented; they check transport only. Swagger Try it out is enabled to inspect those responses. No auth: synthetic data/trusted local network only; do not expose publicly through Caddy. SQLite on UNO Q is the chosen source of truth. Conversation Mode is a separate local-only stretch feature, not part of this HTTP contract. JSON timestamps require offsets; IDs are UUIDs. Never automatically select/speak predictions.",
            },
            "servers": [
                {
                    "url": "/",
                    "description": "Same origin (works through Caddy without hard-coded hostname)",
                }
            ],
            "tags": [
                {"name": name}
                for name in ("profile", "aac", "learn", "legacy", "documentation")
            ],
            "paths": paths,
            "components": {"schemas": deepcopy(SCHEMAS)},
            "x-websocket": {
                "path": "/ws/input/",
                "status": "implemented",
                "group": "input",
                "message": ref("InputMessage"),
                "example": {"action": "SPEAK", "source": "button"},
                "description": "Single local active board. Arduino sends plain serial lines at 9600 baud (PREV, NEXT, SELECT, DELETE, SPEAK, VOICE, TOUCH); the bridge maps them to InputMessage (VOICE and TOUCH become SELECT). Space/Enter handled by frontend. No conversation streaming on this group.",
            },
        }
    )
