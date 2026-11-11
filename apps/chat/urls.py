from django.urls import path
from django.http import JsonResponse


def chat_ping_view(request):
    return JsonResponse({"status": "ready", "module": "chat"})


app_name = "chat"

urlpatterns = [
    path("ping/", chat_ping_view, name="ping"),
]
