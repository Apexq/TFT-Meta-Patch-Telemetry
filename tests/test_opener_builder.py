"""
Tests for Task 5: Opener Builder & Item Pivot Tool.
"""

import json
import pytest
from django.test import Client
from django.core.management import call_command


@pytest.mark.django_db
def test_opener_builder_elements_rendered_in_home():
    call_command("sync_tft_meta")
    client = Client()
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    assert "opener-builder-drawer" in html
    assert "opener-items-strip" in html
    assert "toggleOpenerItem" in html
    assert "submitOpenerQuery" in html
    assert "Geçiş Planını Çıkar" in html


@pytest.mark.django_db
def test_send_message_with_selected_opener_items():
    call_command("sync_tft_meta")
    client = Client()

    # User selects Guinsoo and Warmog
    resp = client.post(
        "/chat/send/",
        data=json.dumps({
            "query": "Elimde Guinsoo var erken aşamadan 4-2 pivot planı ver",
            "mode": "OPENER_BUILDER",
            "selected_items": ["DA_GuinsoosRageblade", "DA_WarmogsArmor"],
        }),
        content_type="application/json",
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    msg = data["message"]
    assert len(msg["ui_cards"]) > 0

    first_card = msg["ui_cards"][0]
    assert first_card.get("card_type") == "composition"
    assert "level_schedule" in first_card
    assert len(first_card["level_schedule"]) > 0
