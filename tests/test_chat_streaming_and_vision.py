"""
Tests for Phase 2: SSE Streaming (/chat/stream/), 4x7 Hex Positioning Card, and Vision Screenshot Upload.
"""

import io
import json
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.contrib.auth.models import User

from apps.chat.models import ChatMessage, ChatSession
from apps.telemetry.services import sync_telemetry_payload


def _make_png_bytes(width: int = 32, height: int = 32) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(240, 195, 116))
    img.save(buf, format="PNG")
    return buf.getvalue()


def _parse_sse_events(raw_bytes: bytes):
    text = raw_bytes.decode("utf-8")
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_name = None
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev_name = line[6:].strip()
            elif line.startswith("data:"):
                data_str += line[5:].strip()
        if ev_name and data_str:
            events.append((ev_name, json.loads(data_str)))
    return events


SAMPLE_COMP_REPORT = {
    "versions": {"previous_label": "18.7", "latest_label": "18.8", "pbe_label": "19.1 (PBE)"},
    "cdragon_version": "16.24",
    "fingerprint": "fp-stream-test",
    "live_meta": {
        "matches_analyzed": 500,
        "compositions": [
            {
                "cluster_id": "426000",
                "comp_name": "4 Meclis LeBlanc",
                "comp_name_en": "4 Cabal LeBlanc",
                "tier": "S",
                "levelling": "Fast 8",
                "meta_status": "STRONG",
                "master_stats": {"avg_placement": 3.85, "top4_rate": 61.2, "win_rate": 16.5},
                "team_planner_code": "0234567890TFTSet18",
                "units": [{"name": "LeBlanc", "cost": 4, "icon": "", "is_carry": True}],
                "board_grid": [
                    [{"name": "Tank", "cost": 4, "icon": "", "is_carry": False}, None, None, None, None, None, None],
                    [None, None, None, None, None, None, None],
                    [None, None, None, None, None, None, None],
                    [None, None, None, None, None, None, {"name": "LeBlanc", "cost": 4, "icon": "", "is_carry": True}],
                ],
            }
        ],
    },
    "augments": {"augments": []},
    "mechanics": {"encounters": [], "charms": []},
}

SAMPLE_COMP_RAG = {
    "chunks": [
        {"id": "overview", "type": "overview", "title": "Patch 18.8", "keywords": "patch 18.8 meta", "text": "Overview."},
        {"id": "comp:426000", "type": "composition", "title": "4 Meclis LeBlanc", "keywords": "leblanc meclis fast 8 dizilim tahta", "text": "LeBlanc Fast 8 meta comp."},
    ]
}


@pytest.mark.django_db
class TestStreamingAndVision:
    def test_sse_stream_emits_ordered_events_and_positioning_card(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        sync_telemetry_payload(SAMPLE_COMP_REPORT, SAMPLE_COMP_RAG)

        client = Client()
        resp = client.post(
            "/chat/stream/",
            data=json.dumps({"query": "LeBlanc tahta dizilimi ve hex konumu nasıl olmalı?", "mode": "META_COACH"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/event-stream")
        assert resp["X-Accel-Buffering"] == "no"

        raw = b"".join(resp.streaming_content)
        events = _parse_sse_events(raw)
        names = [e[0] for e in events]

        assert names[0] == "meta"
        assert "token" in names
        assert "cards" in names
        assert names[-1] == "done"

        cards_payload = dict(events)["cards"]["ui_cards"]
        assert any(c.get("card_type") == "positioning_board" for c in cards_payload)

        # Persisted assistant message matches
        done_payload = dict(events)["done"]
        saved_msg = ChatMessage.objects.get(id=done_payload["message_id"])
        assert saved_msg.role == "assistant"
        assert len(saved_msg.content_markdown) > 0

    def test_stream_rejects_invalid_image_without_consuming_quota(self):
        client = Client()
        bad_file = SimpleUploadedFile("fake.png", b"not-a-real-image-bytes", content_type="image/png")
        resp = client.post(
            "/chat/stream/",
            data={"query": "Tahtama bak", "image": bad_file},
        )
        assert resp.status_code == 400
        assert client.session.get("guest_quota_used", 0) == 0

    def test_stream_accepts_valid_png_screenshot_and_marks_has_image(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        sync_telemetry_payload(SAMPLE_COMP_REPORT, SAMPLE_COMP_RAG)

        client = Client()
        png_file = SimpleUploadedFile("board.png", _make_png_bytes(64, 64), content_type="image/png")
        resp = client.post(
            "/chat/stream/",
            data={"query": "Bu ekran görüntüsündeki tahtamla neye pivot edeyim?", "image": png_file},
        )
        assert resp.status_code == 200
        raw = b"".join(resp.streaming_content)
        events = _parse_sse_events(raw)
        meta = dict(events)["meta"]
        assert meta["has_image"] is True

        user_msg = ChatMessage.objects.get(id=meta["user_message_id"])
        assert user_msg.has_image is True

    def test_stream_enforces_session_ownership_403(self):
        owner = User.objects.create_user(username="owner_sse", password="Password123!")
        other = User.objects.create_user(username="other_sse", password="Password123!")
        sess = ChatSession.objects.create(user=owner, title="Private SSE Chat")

        client = Client()
        client.force_login(other)
        resp = client.post(
            "/chat/stream/",
            data=json.dumps({"query": "Merhaba", "session_id": str(sess.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 403
