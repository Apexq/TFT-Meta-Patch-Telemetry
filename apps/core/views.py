"""
Views for apps.core: Chat-First home page and live telemetry drawers.
"""

from __future__ import annotations

from django.shortcuts import render
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from apps.telemetry.models import PatchSnapshot
from apps.chat.models import ChatSession


def chat_home_view(request):
    """
    Main Chat-First homepage view for TFT Set 18 AI Coach.
    """
    active_snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    report = active_snapshot.full_report_json if active_snapshot else {}
    matcher_items = report.get("tier_lists", {}).get("matcher_items", [])
    
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

    # Historical Session Loading with strict authorization
    session_id_param = request.GET.get("session")
    current_session = None
    chat_messages = []
    if session_id_param:
        try:
            target_session = ChatSession.objects.filter(id=session_id_param).first()
            if target_session:
                if request.user.is_authenticated:
                    if target_session.user == request.user:
                        current_session = target_session
                else:
                    if session_key and target_session.guest_session_key == session_key and target_session.user is None:
                        current_session = target_session
                if current_session:
                    chat_messages = list(current_session.messages.order_by("created_at"))
        except (ValueError, TypeError, ValidationError):
            pass

    context = {
        "active_snapshot": active_snapshot,
        "matcher_items": matcher_items,
        "chat_sessions": chat_sessions,
        "user_display": user_display,
        "quota_left": quota_left,
        "plan_tier": plan_tier,
        "current_session": current_session,
        "chat_messages": chat_messages,
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
