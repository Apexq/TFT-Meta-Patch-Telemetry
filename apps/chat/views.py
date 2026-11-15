"""
Views for apps.chat: Handles chat messages, Generative UI cards, and feedback.
"""

from __future__ import annotations

import json
import time
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.chat.models import ChatSession, ChatMessage
from apps.chat.llm_service import AICoachLLMService
from apps.telemetry.services import TelemetryRAGService


@csrf_exempt
@require_POST
def send_message_view(request):
    """
    Primary endpoint for processing user chat queries and returning
    assistant responses paired with Generative UI cards.
    """
    start_time = time.time()
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        body = {}

    raw_query = body.get("query", "")
    if not isinstance(raw_query, str):
        return JsonResponse({"error": "Soru metni geçersiz."}, status=400)
    query = raw_query.strip()
    mode = body.get("mode", "META_COACH")
    session_id = body.get("session_id")
    selected_items = body.get("selected_items", [])
    match_id = body.get("match_id")
    raw_lang = body.get("lang")

    if not query:
        return JsonResponse({"error": "Soru metni boş olamaz."}, status=400)

    # Ensure guest session key & validate existing ChatSession ownership before consuming quota
    session_key = request.session.session_key or ""
    if not session_key:
        request.session.save()
        session_key = request.session.session_key

    session = None
    if session_id:
        try:
            session = ChatSession.objects.filter(id=session_id).first()
        except (ValueError, TypeError, ValidationError):
            return JsonResponse({"error": "Geçersiz sohbet oturumu kimliği."}, status=400)

        if session:
            if request.user.is_authenticated:
                if session.user_id != request.user.id:
                    return JsonResponse({"error": "Yetkisiz işlem: Bu sohbet oturumu size ait değil."}, status=403)
            else:
                if not session_key or session.guest_session_key != session_key or session.user_id is not None:
                    return JsonResponse({"error": "Yetkisiz işlem: Bu misafir sohbeti size ait değil."}, status=403)

    # Quota Enforcement
    profile = None
    if request.user.is_authenticated:
        from apps.accounts.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if not profile.consume_quota():
            return JsonResponse({
                "error": f"Günlük soru limitinize ulaştınız ({profile.daily_quota_limit} soru/gün). Yarın tekrar deneyin veya planınızı yükseltin.",
                "quota_exceeded": True,
            }, status=429)
    else:
        guest_used = request.session.get("guest_quota_used", 0)
        guest_limit = 30
        if guest_used >= guest_limit:
            return JsonResponse({
                "error": "Misafir oturumu soru limitinize ulaştınız (30 soru). Devam etmek için ücretsiz kayıt olun!",
                "quota_exceeded": True,
            }, status=429)
        request.session["guest_quota_used"] = guest_used + 1
        request.session.modified = True

    if raw_lang in ("tr", "en"):
        preferred_lang = raw_lang
    elif profile and profile.preferred_lang in ("tr", "en"):
        preferred_lang = profile.preferred_lang
    else:
        preferred_lang = "tr"

    attached_match = None
    if match_id:
        from apps.riot_sync.models import PlayerMatchCache
        puuid = str(body.get("puuid") or "").strip()
        if not puuid and profile and profile.riot_puuid:
            puuid = profile.riot_puuid
        qs = PlayerMatchCache.objects.filter(match_id=str(match_id).strip())
        attached_match = (qs.filter(puuid=puuid).first() or qs.first()) if puuid else qs.first()

    if not session:
        session_title = query[:40] + ("..." if len(query) > 40 else "")
        session = ChatSession.objects.create(
            user=request.user if request.user.is_authenticated else None,
            guest_session_key=session_key if not request.user.is_authenticated else "",
            title=session_title,
            mode=mode if (mode != "META_COACH" or not attached_match) else "POST_GAME",
            selected_items_json=selected_items,
            attached_match=attached_match,
        )
    else:
        if attached_match:
            session.attached_match = attached_match
            session.save(update_fields=["attached_match"])
        elif session.attached_match:
            attached_match = session.attached_match

    # Save User Message
    user_msg = ChatMessage.objects.create(
        session=session,
        role="user",
        content_markdown=query,
    )

    # Collect recent conversation history (up to last 6 messages, chronological order)
    prior_msgs = list(
        session.messages.exclude(id=user_msg.id).order_by("-created_at")[:6]
    )
    prior_msgs.reverse()
    history = [
        {"role": m.role, "content": m.content_markdown}
        for m in prior_msgs
    ]
    recent_history_text = " ".join(m.content_markdown for m in prior_msgs[-2:])

    # Retrieve matching RAG chunks & candidate Generative UI card payloads
    rag_result = TelemetryRAGService.retrieve_chunks_and_cards(
        query=query,
        top_k=8,
        preferred_lang=preferred_lang,
        selected_items=selected_items,
        history_text=recent_history_text,
    )

    # Generate AI Coach Response (AI decides both reply and which Hextech cards to render)
    ai_result = AICoachLLMService.generate_coach_response(
        query=query,
        retrieved_chunks=rag_result["chunks"],
        ui_cards=rag_result["ui_cards"],
        preferred_lang=preferred_lang,
        mode=mode,
        history=history,
        attached_match=attached_match,
    )

    ui_cards = list(ai_result.get("ui_cards", []))
    if attached_match:
        match_card = {
            "card_type": "match_review",
            "match_id": attached_match.match_id,
            "placement": attached_match.placement,
            "level": attached_match.level,
            "last_round": attached_match.last_round,
            "gold_left": attached_match.gold_left,
            "summary_headline": (attached_match.ai_diagnosis_cache or {}).get("summary_headline", f"#{attached_match.placement} Sıralama Analizi"),
            "is_heavily_contested": (attached_match.lobby_contested_json or {}).get("is_heavily_contested", False),
            "contested_units": (attached_match.lobby_contested_json or {}).get("contested_units", []),
            "critical_mistakes": (attached_match.ai_diagnosis_cache or {}).get("critical_mistakes", []),
            "recommendations": (attached_match.ai_diagnosis_cache or {}).get("recommendations", []),
        }
        ui_cards.insert(0, match_card)

    latency_ms = int((time.time() - start_time) * 1000)

    # Save Assistant Message with AI-selected UI cards
    assistant_msg = ChatMessage.objects.create(
        session=session,
        role="assistant",
        content_markdown=ai_result["content"],
        ui_cards_json=ui_cards,
        cited_chunk_ids=rag_result["cited_chunk_ids"],
        latency_ms=latency_ms,
        model_used=ai_result["model_used"],
    )

    # If requested via HTMX, return rendered partial HTML
    if request.headers.get("HX-Request"):
        return render(request, "partials/message_bubble.html", {"message": assistant_msg})

    quota_remaining = (
        (profile.daily_quota_limit - profile.daily_quota_used) if request.user.is_authenticated and profile and profile.plan_tier != "ADMIN"
        else ("∞" if request.user.is_authenticated else max(0, 30 - request.session.get("guest_quota_used", 0)))
    )

    return JsonResponse({
        "session_id": str(session.id),
        "user_message_id": user_msg.id,
        "quota_left": quota_remaining,
        "message": {
            "id": assistant_msg.id,
            "role": "assistant",
            "content": assistant_msg.content_markdown,
            "ui_cards": assistant_msg.ui_cards_json,
            "latency_ms": assistant_msg.latency_ms,
            "model_used": assistant_msg.model_used,
        }
    })


@require_POST
def message_feedback_view(request, message_id: int):
    """Saves user thumbs up/down vote for a response with session ownership verification."""
    try:
        body = json.loads(request.body.decode("utf-8"))
        vote = int(body.get("vote", 0))
    except Exception:
        vote = 0

    msg = ChatMessage.objects.select_related("session").filter(id=message_id).first()
    if msg and vote in (1, -1, 0):
        sess = msg.session
        if sess.user_id is not None:
            if not request.user.is_authenticated or sess.user_id != request.user.id:
                return JsonResponse({"error": "Yetkisiz işlem."}, status=403)
        elif sess.guest_session_key:
            session_key = request.session.session_key or ""
            if request.user.is_authenticated or not session_key or sess.guest_session_key != session_key:
                return JsonResponse({"error": "Yetkisiz işlem."}, status=403)

        msg.feedback = vote
        msg.save(update_fields=["feedback"])
        return JsonResponse({"status": "saved", "feedback": vote})

    return JsonResponse({"error": "Geçersiz mesaj veya oy"}, status=400)


@require_POST
def delete_session_view(request, session_id):
    """
    Deletes an individual ChatSession and its cascading messages.
    Strictly checks ownership for authenticated users and guest session keys.
    Returns 403 on authorization failure, 404 if not found.
    """
    session = ChatSession.objects.filter(id=session_id).first()
    if not session:
        return JsonResponse({"error": "Sohbet oturumu bulunamadı."}, status=404)

    # Strict Authorization Check
    if request.user.is_authenticated:
        if session.user != request.user:
            return JsonResponse({"error": "Yetkisiz işlem: Bu sohbet oturumu size ait değil."}, status=403)
    else:
        session_key = request.session.session_key or ""
        if not session_key or session.guest_session_key != session_key or session.user is not None:
            return JsonResponse({"error": "Yetkisiz işlem: Bu misafir sohbeti size ait değil."}, status=403)

    # Cascading deletion via models.CASCADE on ChatMessage
    session.delete()
    return JsonResponse({"status": "success", "session_id": str(session_id)})

