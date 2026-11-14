"""
URL routing for apps.riot_sync.
"""

from django.urls import path
from apps.riot_sync import views

app_name = "riot_sync"

urlpatterns = [
    path("player-matches/", views.fetch_player_matches_view, name="player_matches"),
    path("match/<str:match_id>/analyze/", views.analyze_match_view, name="analyze_match"),
]
