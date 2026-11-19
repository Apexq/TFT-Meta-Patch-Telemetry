from django.urls import path
from .views import send_message_view, stream_message_view, message_feedback_view, delete_session_view

app_name = "chat"

urlpatterns = [
    path("send/", send_message_view, name="send_message"),
    path("stream/", stream_message_view, name="stream_message"),
    path("feedback/<int:message_id>/", message_feedback_view, name="feedback"),
    path("sessions/<uuid:session_id>/delete/", delete_session_view, name="delete_session"),
]

