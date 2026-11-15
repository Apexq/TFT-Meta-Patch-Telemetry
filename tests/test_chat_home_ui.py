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


@pytest.mark.django_db
def test_ui_hardening_escapes_renders_cards_and_legal_footer():
    from django.contrib.auth import get_user_model
    from django.template.loader import render_to_string

    call_command("sync_tft_meta")
    client = Client()
    html = client.get("/").content.decode("utf-8")

    # Mandatory Riot Legal Jibber Jabber disclaimer, XSS escaping, newline regex, encounter/charm JS renderers
    assert "Legal Jibber Jabber" in html
    assert "isn't endorsed by Riot Games" in html
    assert "function escapeHtml(" in html
    assert r".replace(/\r?\n/g, '<br>')" in html
    assert "card.card_type === 'encounter'" in html
    assert "card.card_type === 'charm'" in html
    assert "prependSidebarSession(" in html
    assert '<form method="post"' not in html  # guest state doesn't render logout form until authenticated

    # Saved comp_card.html renders 3-star on top-right, encounter, charm, and match_review details
    rendered_cards = render_to_string(
        "partials/comp_card.html",
        {
            "cards": [
                {
                    "card_type": "composition",
                    "tier": "S",
                    "comp_name": "Fast 9",
                    "levelling": "Fast 9",
                    "avg_placement": 3.5,
                    "top4_rate": 65.0,
                    "units": [{"name": "Lux", "cost": 5, "icon": "", "is_carry": True, "is_three_star": True}],
                },
                {
                    "card_type": "encounter",
                    "name": "Altın Şöleni",
                    "category": "Eklenti",
                    "tempo_rating": "Fast 8",
                    "post_spawn": "Tüm eklentiler altın.",
                },
                {
                    "card_type": "charm",
                    "name": "Artçı Sarsıntı",
                    "cost": 2,
                    "desc": "Sersemletir.",
                    "rec_tr": "Alınmalı.",
                },
                {
                    "card_type": "match_review",
                    "placement": 6,
                    "level": 8,
                    "last_round": "5-2",
                    "gold_left": 20,
                    "contested_units": [{"unit_name": "LeBlanc", "player_tier": 2, "opponents_count": 2, "pool_depleted_pct": 60.0, "severity": "HIGH"}],
                    "critical_mistakes": ["Dead Gold hatası"],
                    "recommendations": ["All-in at"],
                },
            ]
        },
    )
    assert "top-0 right-0" in rendered_cards
    assert "Altın Şöleni" in rendered_cards
    assert "Artçı Sarsıntı" in rendered_cards
    assert "Dead Gold hatası" in rendered_cards
    assert "All-in at" in rendered_cards

    # Profile progress bar computes exact percentage and uses POST logout form
    User = get_user_model()
    u = User.objects.create_user(username="ui_prof_u", password="password123")
    u.profile.daily_quota_used = 15
    u.profile.daily_quota_limit = 30
    u.profile.save(update_fields=["daily_quota_used", "daily_quota_limit"])
    client.force_login(u)
    prof_html = client.get("/accounts/profile/").content.decode("utf-8")
    assert "width: 50%;" in prof_html
    assert 'action="/accounts/logout/"' in prof_html
