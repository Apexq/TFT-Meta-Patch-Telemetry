"""
Views for apps.chat: Handles chat messages (JSON + SSE Streaming + Vision Screenshot upload),
Generative UI cards, feedback, and session management.
"""

from __future__ import annotations

import base64
import io
import json
import time
from typing import Any, Dict, Optional, Tuple

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from apps.chat.llm_service import AICoachLLMService
from apps.chat.models import ChatMessage, ChatSession
from apps.telemetry.services import TelemetryRAGService

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_IMAGE_WIDTH = 1600
ALLOWED_PIL_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def _validate_and_encode_image(
    uploaded_file: Any = None,
    base64_str: str = "",
) -> Optional[Dict[str, str]]:
    """
    Validates an uploaded or base64-encoded screenshot using Pillow.
    Ensures format is PNG/JPEG/WEBP, size <= 5MB, and resizes width > 1600px.
    Raises ValueError on invalid/corrupted input.
    """
    raw_bytes: Optional[bytes] = None

    if uploaded_file is not None:
        if getattr(uploaded_file, "size", 0) > MAX_IMAGE_BYTES:
            raise ValueError("Ekran görüntüsü en fazla 5 MB olabilir.")
        raw_bytes = uploaded_file.read()
    elif base64_str:
        cleaned = base64_str.strip()
        if "," in cleaned and cleaned.startswith("data:"):
            cleaned = cleaned.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(cleaned, validate=True)
        except Exception:
            raise ValueError("Geçersiz görsel verisi (base64 çözümlenemedi).")
        if len(raw_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("Ekran görüntüsü en fazla 5 MB olabilir.")
    else:
        return None

    if not raw_bytes:
        return None

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_PIL_FORMATS:
                raise ValueError("Yalnızca PNG, JPEG veya WEBP ekran görüntüsü yükleyebilirsiniz.")
            img.load()
            if img.width > MAX_IMAGE_WIDTH:
                ratio = MAX_IMAGE_WIDTH / float(img.width)
                new_h = max(1, int(img.height * ratio))
                img = img.resize((MAX_IMAGE_WIDTH, new_h), Image.Resampling.LANCZOS)
                out_buf = io.BytesIO()
                save_img = img.convert("RGB") if fmt == "JPEG" and img.mode not in ("RGB", "L") else img
                save_img.save(out_buf, format=fmt, quality=85)
                raw_bytes = out_buf.getvalue()
            mime_type = ALLOWED_PIL_FORMATS[fmt]
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError):
        raise ValueError("Geçersiz veya bozuk görsel dosyası.")

    return {
        "mime_type": mime_type,
        "base64_data": base64.b64encode(raw_bytes).decode("ascii"),
    }


def _parse_chat_request(request) -> Tuple[Dict[str, Any], Optional[Any]]:
    """Extracts structured payload & optional uploaded image from JSON or multipart/form-data."""
    content_type = (request.content_type or "").lower()
    if "multipart/form-data" in content_type:
        body: Dict[str, Any] = {
            "query": request.POST.get("query", ""),
            "mode": request.POST.get("mode", "META_COACH"),
            "session_id": request.POST.get("session_id") or None,
            "match_id": request.POST.get("match_id") or None,
            "puuid": request.POST.get("puuid") or "",
            "lang": request.POST.get("lang") or None,
        }
        raw_items = request.POST.get("selected_items", "[]")
        try:
            body["selected_items"] = json.loads(raw_items) if isinstance(raw_items, str) else []
        except Exception:
            body["selected_items"] = []
        return body, request.FILES.get("image")

    try:
        body = json.loads(request.body.decode("utf-8"))
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    return body, None


def _build_match_review_card(attached_match) -> Dict[str, Any]:
    return {
        "card_type": "match_review",
        "match_id": attached_match.match_id,
        "placement": attached_match.placement,
        "level": attached_match.level,
        "last_round": attached_match.last_round,
        "gold_left": attached_match.gold_left,
        "summary_headline": (attached_match.ai_diagnosis_cache or {}).get(
            "summary_headline", f"#{attached_match.placement} Sıralama Analizi"
        ),
        "is_heavily_contested": (attached_match.lobby_contested_json or {}).get("is_heavily_contested", False),
        "contested_units": (attached_match.lobby_contested_json or {}).get("contested_units", []),
        "critical_mistakes": (attached_match.ai_diagnosis_cache or {}).get("critical_mistakes", []),
        "recommendations": (attached_match.ai_diagnosis_cache or {}).get("recommendations", []),
    }


def _prepare_chat_turn(request) -> Tuple[Optional[Dict[str, Any]], Optional[JsonResponse]]:
    """
    Validates query/image/session ownership, enforces atomic quota, persists user message,
    and executes RAG retrieval. Returns (context_dict, None) or (None, error_response).
    """
    body, uploaded_image = _parse_chat_request(request)

    raw_query = body.get("query", "")
    if not isinstance(raw_query, str):
        return None, JsonResponse({"error": "Soru metni geçersiz."}, status=400)
    query = raw_query.strip()
    mode = body.get("mode", "META_COACH") or "META_COACH"
    session_id = body.get("session_id")
    selected_items = body.get("selected_items", []) or []
    match_id = body.get("match_id")
    raw_lang = body.get("lang")

    # Validate optional image BEFORE consuming quota
    try:
        image_data = _validate_and_encode_image(
            uploaded_file=uploaded_image,
            base64_str=str(body.get("image_base64") or ""),
        )
    except ValueError as img_err:
        return None, JsonResponse({"error": str(img_err)}, status=400)

    if not query and image_data:
        query = "Bu oyun içi ekran görüntüsündeki tahtamı, eşyalarımı ve en iyi pivot / dizilim hamlesini analiz et."
    if not query:
        return None, JsonResponse({"error": "Soru metni boş olamaz."}, status=400)

    session_key = request.session.session_key or ""
    if not session_key:
        request.session.save()
        session_key = request.session.session_key

    session = None
    if session_id:
        try:
            session = ChatSession.objects.filter(id=session_id).first()
        except (ValueError, TypeError, ValidationError):
            return None, JsonResponse({"error": "Geçersiz sohbet oturumu kimliği."}, status=400)

        if session:
            if request.user.is_authenticated:
                if session.user_id != request.user.id:
                    return None, JsonResponse(
                        {"error": "Yetkisiz işlem: Bu sohbet oturumu size ait değil."}, status=403
                    )
            else:
                if not session_key or session.guest_session_key != session_key or session.user_id is not None:
                    return None, JsonResponse(
                        {"error": "Yetkisiz işlem: Bu misafir sohbeti size ait değil."}, status=403
                    )

    # Atomic Quota Enforcement
    profile = None
    if request.user.is_authenticated:
        from apps.accounts.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if not profile.consume_quota():
            return None, JsonResponse({
                "error": f"Günlük soru limitinize ulaştınız ({profile.daily_quota_limit} soru/gün). Yarın tekrar deneyin veya PRO planına yükseltin.",
                "quota_exceeded": True,
            }, status=429)
    else:
        guest_used = request.session.get("guest_quota_used", 0)
        guest_limit = 30
        if guest_used >= guest_limit:
            return None, JsonResponse({
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

    user_msg = ChatMessage.objects.create(
        session=session,
        role="user",
        content_markdown=query,
        has_image=bool(image_data),
    )

    prior_msgs = list(session.messages.exclude(id=user_msg.id).order_by("-created_at")[:6])
    prior_msgs.reverse()
    history = [{"role": m.role, "content": m.content_markdown} for m in prior_msgs]
    recent_history_text = " ".join(m.content_markdown for m in prior_msgs[-2:])

    rag_result = TelemetryRAGService.retrieve_chunks_and_cards(
        query=query,
        top_k=8,
        preferred_lang=preferred_lang,
        selected_items=selected_items,
        history_text=recent_history_text,
        mode=mode,
    )

    quota_remaining = (
        (profile.daily_quota_limit - profile.daily_quota_used)
        if request.user.is_authenticated and profile and profile.plan_tier != "ADMIN"
        else ("∞" if request.user.is_authenticated else max(0, 30 - request.session.get("guest_quota_used", 0)))
    )

    return {
        "query": query,
        "mode": mode,
        "session": session,
        "user_msg": user_msg,
        "history": history,
        "rag_result": rag_result,
        "preferred_lang": preferred_lang,
        "attached_match": attached_match,
        "image_data": image_data,
        "quota_remaining": quota_remaining,
    }, None


@csrf_exempt
@require_POST
def send_message_view(request):
    """
    Primary JSON/HTMX endpoint for processing user chat queries and returning
    assistant responses paired with Generative UI cards.
    """
    start_time = time.time()
    ctx, err_resp = _prepare_chat_turn(request)
    if err_resp is not None:
        return err_resp

    ai_result = AICoachLLMService.generate_coach_response(
        query=ctx["query"],
        retrieved_chunks=ctx["rag_result"]["chunks"],
        ui_cards=ctx["rag_result"]["ui_cards"],
        preferred_lang=ctx["preferred_lang"],
        mode=ctx["mode"],
        history=ctx["history"],
        attached_match=ctx["attached_match"],
        image_data=ctx["image_data"],
    )

    ui_cards = list(ai_result.get("ui_cards", []))
    if ctx["attached_match"]:
        ui_cards.insert(0, _build_match_review_card(ctx["attached_match"]))

    latency_ms = int((time.time() - start_time) * 1000)

    assistant_msg = ChatMessage.objects.create(
        session=ctx["session"],
        role="assistant",
        content_markdown=ai_result["content"],
        ui_cards_json=ui_cards,
        cited_chunk_ids=ctx["rag_result"]["cited_chunk_ids"],
        latency_ms=latency_ms,
        model_used=ai_result["model_used"],
    )

    if request.headers.get("HX-Request"):
        return render(request, "partials/message_bubble.html", {"message": assistant_msg})

    return JsonResponse({
        "session_id": str(ctx["session"].id),
        "user_message_id": ctx["user_msg"].id,
        "quota_left": ctx["quota_remaining"],
        "has_image": bool(ctx["image_data"]),
        "message": {
            "id": assistant_msg.id,
            "role": "assistant",
            "content": assistant_msg.content_markdown,
            "ui_cards": assistant_msg.ui_cards_json,
            "latency_ms": assistant_msg.latency_ms,
            "model_used": assistant_msg.model_used,
        },
    })


def _sse_event(event_name: str, data: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@csrf_exempt
@require_POST
def stream_message_view(request):
    """
    Server-Sent Events (SSE) streaming chat endpoint (POST /chat/stream/).
    Supports JSON or multipart/form-data (with optional screenshot upload).
    Emits: `meta` -> `token`* -> `cards` -> `done`.
    """
    start_time = time.time()
    ctx, err_resp = _prepare_chat_turn(request)
    if err_resp is not None:
        return err_resp

    def event_stream():
        yield _sse_event("meta", {
            "session_id": str(ctx["session"].id),
            "user_message_id": ctx["user_msg"].id,
            "quota_left": ctx["quota_remaining"],
            "title": ctx["session"].title,
            "has_image": bool(ctx["image_data"]),
        })

        final_content = ""
        final_cards = []
        final_model = "telemetry-rag-engine"

        for event in AICoachLLMService.stream_coach_response(
            query=ctx["query"],
            retrieved_chunks=ctx["rag_result"]["chunks"],
            ui_cards=ctx["rag_result"]["ui_cards"],
            preferred_lang=ctx["preferred_lang"],
            mode=ctx["mode"],
            history=ctx["history"],
            attached_match=ctx["attached_match"],
            image_data=ctx["image_data"],
        ):
            etype = event.get("type")
            if etype == "token":
                yield _sse_event("token", {"delta": event.get("delta", "")})
            elif etype == "cards":
                cards = list(event.get("ui_cards") or [])
                if ctx["attached_match"]:
                    cards.insert(0, _build_match_review_card(ctx["attached_match"]))
                final_cards = cards
                yield _sse_event("cards", {"ui_cards": cards})
            elif etype == "done":
                final_content = event.get("content", "")
                final_model = event.get("model_used", final_model)

        latency_ms = int((time.time() - start_time) * 1000)
        assistant_msg = ChatMessage.objects.create(
            session=ctx["session"],
            role="assistant",
            content_markdown=final_content,
            ui_cards_json=final_cards,
            cited_chunk_ids=ctx["rag_result"]["cited_chunk_ids"],
            latency_ms=latency_ms,
            model_used=final_model,
        )

        yield _sse_event("done", {
            "message_id": assistant_msg.id,
            "model_used": assistant_msg.model_used,
            "latency_ms": assistant_msg.latency_ms,
        })

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


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

    if request.user.is_authenticated:
        if session.user != request.user:
            return JsonResponse({"error": "Yetkisiz işlem: Bu sohbet oturumu size ait değil."}, status=403)
    else:
        session_key = request.session.session_key or ""
        if not session_key or session.guest_session_key != session_key or session.user is not None:
            return JsonResponse({"error": "Yetkisiz işlem: Bu misafir sohbeti size ait değil."}, status=403)

    session.delete()
    return JsonResponse({"status": "success", "session_id": str(session_id)})
