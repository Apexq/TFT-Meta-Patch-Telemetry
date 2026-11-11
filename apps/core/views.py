"""
Views for apps.core: Chat-First home page and live telemetry drawers.
"""

from __future__ import annotations

from django.shortcuts import render
from django.http import HttpResponse
from apps.telemetry.models import PatchSnapshot
from apps.chat.models import ChatSession


def chat_home_view(request):
    """
    Main Chat-First homepage view for TFT Set 18 AI Coach.
    """
    active_snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    
    # Session handling (Guest or Authenticated User)
    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key

    if request.user.is_authenticated:
        chat_sessions = ChatSession.objects.filter(user=request.user)[:20]
        user_display = request.user.username
        profile = getattr(request.user, "profile", None)
        quota_left = profile.daily_quota_limit - profile.daily_quota_used if profile else 30
        plan_tier = profile.plan_tier if profile else "FREE"
    else:
        chat_sessions = ChatSession.objects.filter(guest_session_key=session_key)[:20]
        user_display = "Misafir Oyuncu"
        quota_left = 30
        plan_tier = "FREE"

    context = {
        "active_snapshot": active_snapshot,
        "chat_sessions": chat_sessions,
        "user_display": user_display,
        "quota_left": quota_left,
        "plan_tier": plan_tier,
        "chat_messages": [],
    }
    return render(request, "chat_home.html", context)


def drawer_meta_view(request):
    """Slide-over drawer content: Master+ Meta Compositions."""
    snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    report = snapshot.full_report_json if snapshot else {}
    comps = report.get("live_meta", {}).get("compositions", [])
    return render(request, "partials/drawer_meta.html", {"active_snapshot": snapshot, "compositions": comps})


def drawer_augments_view(request):
    """Slide-over drawer content: Riot Policy Compliant Augment List."""
    snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    report = snapshot.full_report_json if snapshot else {}
    augments = report.get("augments", {}).get("augments", [])
    return render(request, "partials/drawer_augments.html", {"active_snapshot": snapshot, "augments": augments})


def drawer_mechanics_view(request):
    """Slide-over drawer content: Set 18 Encounters & Shop Charms."""
    snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    report = snapshot.full_report_json if snapshot else {}
    encounters = report.get("mechanics", {}).get("encounters", [])
    charms = report.get("mechanics", {}).get("charms", [])
    return render(request, "partials/drawer_mechanics.html", {"active_snapshot": snapshot, "encounters": encounters, "charms": charms})
