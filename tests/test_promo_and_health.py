"""
Tests for Phase 3: Hybrid PRO PromoCode Redemption, Pricing page, /health/ endpoint & SQLite WAL.
"""

import json
from datetime import timedelta
import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from apps.accounts.models import PromoCode, PromoRedemption, SubscriptionEvent, UserProfile


@pytest.mark.django_db
class TestPromoAndHealth:
    def test_redeem_promo_requires_authentication(self):
        client = Client()
        resp = client.post(
            "/accounts/redeem-code/",
            data=json.dumps({"code": "TFTPRO2026"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_redeem_promo_upgrades_free_to_pro_and_blocks_reuse(self):
        user = User.objects.create_user(username="promo_user", password="Password123!")
        profile, _ = UserProfile.objects.get_or_create(user=user)
        assert profile.plan_tier == "FREE"
        assert profile.daily_quota_limit == 30

        promo = PromoCode.objects.create(code="tftpro2026", target_tier="PRO", max_uses=2, is_active=True)
        assert promo.code == "TFTPRO2026"

        client = Client()
        client.force_login(user)

        resp = client.post(
            "/accounts/redeem-code/",
            data=json.dumps({"code": "tftpro2026"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_tier"] == "PRO"
        assert data["daily_quota_limit"] == 500

        profile.refresh_from_db()
        promo.refresh_from_db()
        assert profile.plan_tier == "PRO"
        assert profile.daily_quota_limit == 500
        assert promo.uses_count == 1
        assert PromoRedemption.objects.filter(user=user, promo_code=promo).exists()
        assert SubscriptionEvent.objects.filter(user=user, provider="promo", plan_tier="PRO").exists()

        # Double-redeem by same user blocked
        resp_dup = client.post(
            "/accounts/redeem-code/",
            data=json.dumps({"code": "TFTPRO2026"}),
            content_type="application/json",
        )
        assert resp_dup.status_code == 400

    def test_expired_and_exhausted_promo_codes_rejected(self):
        user = User.objects.create_user(username="promo_user2", password="Password123!")
        PromoCode.objects.create(
            code="EXPIRED1",
            expires_at=timezone.now() - timedelta(days=1),
            max_uses=5,
            is_active=True,
        )
        PromoCode.objects.create(
            code="FULL1",
            max_uses=1,
            uses_count=1,
            is_active=True,
        )

        client = Client()
        client.force_login(user)

        r1 = client.post("/accounts/redeem-code/", data=json.dumps({"code": "EXPIRED1"}), content_type="application/json")
        r2 = client.post("/accounts/redeem-code/", data=json.dumps({"code": "FULL1"}), content_type="application/json")
        assert r1.status_code == 400
        assert r2.status_code == 400

    def test_pricing_page_and_health_endpoint(self):
        client = Client()
        r_html = client.get("/accounts/pricing/")
        assert r_html.status_code == 200
        assert "PRO" in r_html.content.decode("utf-8")

        r_json = client.get("/accounts/pricing/?format=json")
        assert r_json.status_code == 200
        assert len(r_json.json()["plans"]) == 2

        r_health = client.get("/health/")
        assert r_health.status_code == 200
        health = r_health.json()
        assert health["status"] == "ok"
        assert health["database"] == "sqlite"
