from django.urls import path
from django.http import JsonResponse


def profile_status_view(request):
    return JsonResponse({"auth": request.user.is_authenticated})


app_name = "accounts"

urlpatterns = [
    path("status/", profile_status_view, name="status"),
]
