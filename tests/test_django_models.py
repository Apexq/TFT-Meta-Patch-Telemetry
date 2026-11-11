"""
Unit tests for Django ORM models and verification endpoints (Task 1).
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.telemetry.models import PatchSnapshot, RAGChunk
from apps.riot_sync.models import PlayerMatchCache
from apps.chat.models import ChatSession, ChatMessage, RateLimitLog

User = get_user_model()


@pytest.mark.django_db
def test_riot_verification_endpoint():
    client = Client()
    resp = client.get("/riot.txt")
    assert resp.status_code == 200
    assert resp.content.decode("utf-8").strip() == "55016fcd-fe08-40f7-bf33-18a2dbc82a60"


@pytest.mark.django_db
def test_user_profile_quota_lifecycle():
    user = User.objects.create_user(username="apexq_tester", password="safe_password_123")
    profile = UserProfile.objects.create(
        user=user,
        riot_game_name="Apexq",
        riot_tag_line="TR1",
        riot_region="TR1",
        daily_quota_limit=2,
    )

    assert profile.can_ask_question() is True
    assert profile.consume_quota() is True
    assert profile.daily_quota_used == 1

    assert profile.consume_quota() is True
    assert profile.daily_quota_used == 2

    # Limit reached
    assert profile.can_ask_question() is False
    assert profile.consume_quota() is False


@pytest.mark.django_db
def test_telemetry_models_and_rag_chunk_payload():
    snapshot = PatchSnapshot.objects.create(
        patch_label="18.6",
        previous_label="18.5",
        pbe_label="18.7",
        cdragon_version="16.22",
        fingerprint="a1b2c3d4e5f67890",
        is_active=True,
        matches_analyzed=50000,
    )

    chunk = RAGChunk.objects.create(
        snapshot=snapshot,
        chunk_id="comp:426000",
        chunk_type="composition",
        title_tr="4 Meclis LeBlanc",
        title_en="4 Coven LeBlanc",
        keywords_normalized="4 meclis leblanc coven fast 8 s tier",
        content_text="[Master+ S-Tier Comp] 4 Coven LeBlanc Fast 8 leveling.",
        ui_card_payload={
            "tier": "S",
            "team_planner_code": "02015022031044051062073084000000TFTSet18",
            "units": [{"name": "LeBlanc", "cost": 4, "is_carry": True}],
        },
    )

    assert chunk.snapshot.patch_label == "18.6"
    assert chunk.ui_card_payload["tier"] == "S"
    assert chunk.ui_card_payload["team_planner_code"].endswith("TFTSet18")


@pytest.mark.django_db
def test_chat_session_and_generative_ui_message():
    session = ChatSession.objects.create(
        title="Guinsoo ile hangi comp gider?",
        guest_session_key="guest_test_abc123",
        mode="META_COACH",
    )

    msg_user = ChatMessage.objects.create(
        session=session,
        role="user",
        content_markdown="Guinsoo ile hangi comp gider?",
    )

    msg_bot = ChatMessage.objects.create(
        session=session,
        role="assistant",
        content_markdown="Yama 18.6'da Guinsoo's Rageblade için en güçlü taşıyıcı Yunara ve Meclis LeBlanc kompozisyonudur.",
        ui_cards_json=[
            {
                "card_type": "composition",
                "title": "4 Meclis LeBlanc",
                "tier": "S",
            }
        ],
        latency_ms=450,
        model_used="gemini-2.5-flash",
    )

    assert session.messages.count() == 2
    assert msg_bot.ui_cards_json[0]["title"] == "4 Meclis LeBlanc"
    assert session.guest_session_key == "guest_test_abc123"


@pytest.mark.django_db
def test_player_match_cache():
    match = PlayerMatchCache.objects.create(
        match_id="TR1_999888777",
        puuid="puuid_test_12345",
        riot_id_display="Besir#TR1",
        region="TR1",
        patch_version="18.6",
        placement=1,
        level=9,
        gold_left=14,
        last_round="6-2",
        player_board_json=[{"unit": "LeBlanc", "stars": 3}],
        active_traits_json=[{"trait": "Coven", "count": 4}],
        augments_selected_json=["Prismatic Party", "Golden Gala"],
        game_datetime=timezone.now(),
    )

    assert match.placement == 1
    assert match.player_board_json[0]["unit"] == "LeBlanc"
