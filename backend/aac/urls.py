"""HTTP business routes only. Conversation streaming and WS input are separate."""

from django.urls import path

from . import views

urlpatterns = [
    path("profile/caregivers", views.caregivers, name="caregivers"),
    path("profile/patients", views.patients, name="patients"),
    path(
        "profile/caregivers/<uuid:id>/patients",
        views.caregiver_patients,
        name="caregiver-patients",
    ),
    path("profile/patients/<uuid:id>", views.patient_detail, name="patient-detail"),
    path("aac/speak", views.speak, name="speak"),
    path("aac/predict", views.predict, name="predict"),
    path("aac/events", views.events, name="events"),
    path("aac/patients/<uuid:id>/events", views.patient_events, name="patient-events"),
    path(
        "learn/patients/<uuid:id>/label-definitions",
        views.label_definitions,
        name="label-definitions",
    ),
    path(
        "learn/label-definitions/<uuid:id>",
        views.definition_detail,
        name="definition-detail",
    ),
    path(
        "learn/events/<uuid:event_id>/labels", views.event_labels, name="event-labels"
    ),
    path("learn/labels/<uuid:id>", views.assignment_detail, name="assignment-detail"),
    path("learn/analyze", views.analyze, name="analyze"),
    path(
        "learn/patients/<uuid:id>/summary",
        views.learning_summary,
        name="learning-summary",
    ),
    path("learn/activate", views.activate, name="activate"),
    path("speak", views.legacy_speak, name="legacy-speak"),
    path("predict", views.legacy_predict, name="legacy-predict"),
    path("log", views.legacy_log, name="legacy-log"),
]
