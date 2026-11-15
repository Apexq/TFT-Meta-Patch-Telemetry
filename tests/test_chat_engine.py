"""
Tests for AI Coach Chat Engine, LLM service, and Generative UI cards.
"""

import json
import pytest
from django.test import Client
from django.core.management import call_command
from apps.chat.models import ChatSession, ChatMessage


@pytest.mark.django_db
def test_send_message_generates_response_and_ui_cards():
    call_command("sync_tft_meta")
    client = Client()

    resp = client.post(
        "/chat/send/",
        data=json.dumps({"query": "LeBlanc comp rehberi", "mode": "META_COACH"}),
        content_type="application/json",
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    msg = data["message"]
    assert msg["role"] == "assistant"
    assert len(msg["content"]) > 0
    assert len(msg["ui_cards"]) > 0

    first_card = msg["ui_cards"][0]
    assert first_card.get("card_type") == "composition"
    assert "team_planner_code" in first_card
    assert first_card["team_planner_code"].endswith("TFTSet18")

    # Verify database persistence
    session_id = data["session_id"]
    session = ChatSession.objects.get(id=session_id)
    assert session.messages.count() == 2  # user + assistant


@pytest.mark.django_db
def test_message_feedback_endpoint():
    call_command("sync_tft_meta")
    session = ChatSession.objects.create(title="Test Feedback Session")
    msg = ChatMessage.objects.create(
        session=session,
        role="assistant",
        content_markdown="Test content",
    )

    client = Client()
    resp = client.post(
        f"/chat/feedback/{msg.id}/",
        data=json.dumps({"vote": 1}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"

    msg.refresh_from_db()
    assert msg.feedback == 1


@pytest.mark.django_db
def test_ai_decides_ui_cards_via_structured_output(monkeypatch):
    """Verifies AI can choose zero cards for simple queries or specific cards when needed."""
    call_command("sync_tft_meta")

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # 1) AI selects NO cards for a simple existence question
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=20: FakeResponse({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "reply": "Yasuo Set 18'de bulunmuyor.",
                            "selected_card_ids": [],
                        })
                    }]
                }
            }]
        }),
    )

    client = Client()
    resp = client.post(
        "/chat/send/",
        data=json.dumps({"query": "yasuo var mi"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"]["content"] == "Yasuo Set 18'de bulunmuyor."
    assert data["message"]["ui_cards"] == []


@pytest.mark.django_db
def test_chat_session_and_feedback_idor_and_validation():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    owner = User.objects.create_user(username="owner_u", password="password123")
    attacker = User.objects.create_user(username="attacker_u", password="password123")

    owner_sess = ChatSession.objects.create(user=owner, title="Owner Private Session")
    owner_msg = ChatMessage.objects.create(session=owner_sess, role="assistant", content_markdown="Secret answer")

    guest_sess = ChatSession.objects.create(user=None, guest_session_key="victim-guest-key", title="Guest Private")
    guest_msg = ChatMessage.objects.create(session=guest_sess, role="assistant", content_markdown="Guest answer")

    # 1. Authenticated attacker cannot hijack owner's session or waste quota on rejected attempt
    attacker_client = Client()
    attacker_client.force_login(attacker)
    resp_hijack = attacker_client.post(
        "/chat/send/",
        data=json.dumps({"query": "hijack", "session_id": str(owner_sess.id)}),
        content_type="application/json",
    )
    assert resp_hijack.status_code == 403
    attacker.profile.refresh_from_db()
    assert attacker.profile.daily_quota_used == 0

    # 2. Attacker cannot submit feedback on owner's or guest's message
    resp_fb_user = attacker_client.post(
        f"/chat/feedback/{owner_msg.id}/",
        data=json.dumps({"vote": -1}),
        content_type="application/json",
    )
    assert resp_fb_user.status_code == 403

    other_guest = Client()
    resp_fb_guest = other_guest.post(
        f"/chat/feedback/{guest_msg.id}/",
        data=json.dumps({"vote": -1}),
        content_type="application/json",
    )
    assert resp_fb_guest.status_code == 403

    # 3. Malformed UUID or non-string query returns 400 (not 500)
    resp_bad_uuid = attacker_client.post(
        "/chat/send/",
        data=json.dumps({"query": "hello", "session_id": "not-a-valid-uuid"}),
        content_type="application/json",
    )
    assert resp_bad_uuid.status_code == 400

    resp_bad_query = attacker_client.post(
        "/chat/send/",
        data=json.dumps({"query": ["list", "not", "str"]}),
        content_type="application/json",
    )
    assert resp_bad_query.status_code == 400


@pytest.mark.django_db
def test_chat_propagates_preferred_lang(monkeypatch):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(username="en_user", password="password123")
    user.profile.preferred_lang = "en"
    user.profile.save(update_fields=["preferred_lang"])

    captured = {}

    def fake_retrieve(**kwargs):
        captured["rag_lang"] = kwargs.get("preferred_lang")
        return {"chunks": [], "ui_cards": [], "cited_chunk_ids": []}

    def fake_llm(**kwargs):
        captured["llm_lang"] = kwargs.get("preferred_lang")
        return {"content": "English reply", "ui_cards": [], "model_used": "test-stub"}

    from apps.telemetry.services import TelemetryRAGService
    from apps.chat.llm_service import AICoachLLMService
    monkeypatch.setattr(TelemetryRAGService, "retrieve_chunks_and_cards", classmethod(lambda cls, **kw: fake_retrieve(**kw)))
    monkeypatch.setattr(AICoachLLMService, "generate_coach_response", classmethod(lambda cls, **kw: fake_llm(**kw)))

    c = Client()
    c.force_login(user)
    resp = c.post("/chat/send/", data=json.dumps({"query": "Best comp?"}), content_type="application/json")
    assert resp.status_code == 200
    assert captured["rag_lang"] == "en"
    assert captured["llm_lang"] == "en"
