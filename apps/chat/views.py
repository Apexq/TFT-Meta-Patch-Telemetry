"""
Views for apps.chat: Handles chat messages, Generative UI cards, and feedback.
"""

from __future__ import annotations

import json
import time
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

    query = body.get("query", "").strip()
    mode = body.get("mode", "META_COACH")
    session_id = body.get("session_id")
    selected_items = body.get("selected_items", [])

    if not query:
        return JsonResponse({"error": "Soru metni boş olamaz."}, status=400)

    # Resolve or create ChatSession
    session_key = request.session.session_key or ""
    if not session_key:
        request.session.save()
        session_key = request.session.session_key

    session = None
    if session_id:
        session = ChatSession.objects.filter(id=session_id).first()

    if not session:
        session_title = query[:40] + ("..." if len(query) > 40 else "")
        session = ChatSession.objects.create(
            user=request.user if request.user.is_authenticated else None,
            guest_session_key=session_key if not request.user.is_authenticated else "",
            title=session_title,
            mode=mode,
            selected_items_json=selected_items,
        )

    # Save User Message
    user_msg = ChatMessage.objects.create(
        session=session,
        role="user",
        content_markdown=query,
    )

    # If query is short or refers to previous comp (e.g. "compta hangi herolar var"), augment query with previous context
    effective_query = query
    recent_messages = session.messages.filter(role="user").exclude(id=user_msg.id).order_by("-created_at")[:2]
    if recent_messages.exists() and any(w in query.lower() for w in ("compta", "bu comp", "tahtada", "erken", "hero", "hangi")):
        prev_text = " ".join(m.content_markdown for m in recent_messages)
        effective_query = f"{prev_text} {query}"

    # Retrieve matching RAG chunks & Generative UI card payloads
    rag_result = TelemetryRAGService.retrieve_chunks_and_cards(
        query=effective_query,
        top_k=6,
        preferred_lang="tr",
        selected_items=selected_items,
    )

    # Generate AI Coach Response
    ai_result = AICoachLLMService.generate_coach_response(
        query=query,
        retrieved_chunks=rag_result["chunks"],
        ui_cards=rag_result["ui_cards"],
        preferred_lang="tr",
        mode=mode,
    )

    latency_ms = int((time.time() - start_time) * 1000)

    # Save Assistant Message
    assistant_msg = ChatMessage.objects.create(
        session=session,
        role="assistant",
        content_markdown=ai_result["content"],
        ui_cards_json=rag_result["ui_cards"],
        cited_chunk_ids=rag_result["cited_chunk_ids"],
        latency_ms=latency_ms,
        model_used=ai_result["model_used"],
    )

    # If requested via HTMX, return rendered partial HTML
    if request.headers.get("HX-Request"):
        return render(request, "partials/message_bubble.html", {"message": assistant_msg})

    return JsonResponse({
        "session_id": str(session.id),
        "user_message_id": user_msg.id,
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
    """Saves user thumbs up/down vote for a response."""
    try:
        body = json.loads(request.body.decode("utf-8"))
        vote = int(body.get("vote", 0))
    except Exception:
        vote = 0

    msg = ChatMessage.objects.filter(id=message_id).first()
    if msg and vote in (1, -1, 0):
        msg.feedback = vote
        msg.save(update_fields=["feedback"])
        return JsonResponse({"status": "saved", "feedback": vote})

    return JsonResponse({"error": "Geçersiz mesaj veya oy"}, status=400)
