"""
URL configuration for TFT Set 18 AI Coach.
"""

from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse

RIOT_VERIFICATION_TOKEN = "55016fcd-fe08-40f7-bf33-18a2dbc82a60"


def riot_verification_view(request):
    """Riot Games developer portal domain verification endpoint."""
    return HttpResponse(RIOT_VERIFICATION_TOKEN, content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("riot.txt", riot_verification_view, name="riot-verification"),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("chat/", include("apps.chat.urls")),
]
