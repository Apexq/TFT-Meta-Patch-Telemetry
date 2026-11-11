"""
Tests for Task 3: Chat-First homepage and slide-over drawers.
"""

import pytest
from django.test import Client
from django.core.management import call_command


@pytest.mark.django_db
def test_chat_home_page_renders_with_hextech_theme():
    call_command("sync_tft_meta")
    client = Client()
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    assert "TFT Set 18 AI Koç" in html
    assert "Yeni Koçluk Sohbeti" in html
    assert "Guinsoo Eşya Analizi" in html
    assert "active-mode-badge" in html
    assert "chat-stream" in html
    assert "chat-input" in html
    assert "toggleVoiceInput" in html


@pytest.mark.django_db
def test_drawers_render_telemetry():
    call_command("sync_tft_meta")
    client = Client()

    # Meta Drawer
    resp_meta = client.get("/drawers/meta/")
    assert resp_meta.status_code == 200
    meta_html = resp_meta.content.decode("utf-8")
    assert "Master+ Kümeleme Verisi" in meta_html
    assert "AI Koç'a Sor" in meta_html

    # Augments Drawer
    resp_aug = client.get("/drawers/augments/")
    assert resp_aug.status_code == 200
    aug_html = resp_aug.content.decode("utf-8")
    assert "Riot Geliştirici Politikalarıyla %100 Uyumlu" in aug_html
    assert "S / A / B / C Tier" in aug_html

    # Mechanics Drawer
    resp_mech = client.get("/drawers/mechanics/")
    assert resp_mech.status_code == 200
    mech_html = resp_mech.content.decode("utf-8")
    assert "Set 18 İmza Mekaniği" in mech_html
