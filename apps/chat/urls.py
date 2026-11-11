from django.urls import path
from .views import send_message_view, message_feedback_view

app_name = "chat"

urlpatterns = [
    path("send/", send_message_view, name="send_message"),
    path("feedback/<int:message_id>/", message_feedback_view, name="feedback"),
]
