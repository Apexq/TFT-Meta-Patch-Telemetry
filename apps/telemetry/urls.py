from django.urls import path
from apps.telemetry.views import telemetry_sync_webhook_view

app_name = "telemetry"

urlpatterns = [
    path("sync/", telemetry_sync_webhook_view, name="sync_webhook"),
]
