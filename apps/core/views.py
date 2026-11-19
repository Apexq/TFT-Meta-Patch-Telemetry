"""
Views for apps.core: Chat-First home page and live telemetry drawers.
"""

from __future__ import annotations

import logging
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.db import connection
from apps.telemetry.models import PatchSnapshot
from apps.chat.models import ChatSession

logger = logging.getLogger("apps.core")


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
        from apps.accounts.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.check_and_reset_quota()
        quota_left = (
            profile.daily_quota_limit - profile.daily_quota_used
            if profile.plan_tier != "ADMIN"
            else "∞"
        )
        plan_tier = profile.plan_tier
    else:
        chat_sessions = ChatSession.objects.filter(guest_session_key=session_key)[:20]
        user_display = "Misafir Oyuncu"
        profile = None
        guest_used = request.session.get("guest_quota_used", 0)
        quota_left = max(0, 30 - guest_used)
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
        "profile": profile,
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


def drawer_pbe_view(request):
    """Slide-over drawer content: Set 19 PBE Catalog, Traits & Early Vertical Synergies."""
    snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    report = snapshot.full_report_json if snapshot else {}
    pbe_preview = report.get("pbe_preview") or {}
    pbe_meta = report.get("pbe_meta") or {}
    pbe_diff = report.get("pbe_diff") or {}
    ai_summary = report.get("ai_summary") or {}
    versions = report.get("versions") or {}
    return render(
        request,
        "partials/drawer_pbe.html",
        {
            "active_snapshot": snapshot,
            "pbe_preview": pbe_preview,
            "pbe_comps": pbe_meta.get("compositions", []),
            "pbe_diff": pbe_diff,
            "ai_summary": ai_summary,
            "pbe_label": versions.get("pbe_label") or (snapshot.pbe_label if snapshot else ""),
        },
    )


def health_check_view(request):
    """Lightweight health endpoint verifying DB connectivity and active telemetry snapshot."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            journal_mode = ""
            if connection.vendor == "sqlite":
                cursor.execute("PRAGMA journal_mode;")
                row = cursor.fetchone()
                journal_mode = str(row[0]) if row else ""
        active_snap = PatchSnapshot.objects.filter(is_active=True).values(
            "patch_label", "pbe_label", "fingerprint", "created_at"
        ).first()
        return JsonResponse({
            "status": "ok",
            "database": connection.vendor,
            "journal_mode": journal_mode,
            "active_patch": active_snap["patch_label"] if active_snap else None,
            "pbe_label": active_snap["pbe_label"] if active_snap else None,
            "snapshot_ready": bool(active_snap),
        })
    except Exception:
        logger.exception("Health check failed")
        return JsonResponse({"status": "error", "detail": "Service unavailable."}, status=503)
