"""
Tests for Task 4: AI Coach Chat Engine, LLM service, and Generative UI cards.
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
