"""
Security hardening verification tests:
- CSRF protection enforced on session-backed chat & riot_sync endpoints
- Privacy-preserving IP-hash rate limiting on login, promo redemption, and guest chat bypass
- No internal exception leakage on /health/
- Pillow decompression bomb pixel cap active
"""

import json
from unittest.mock import patch
import pytest
from PIL import Image
from django.contrib.auth.models import User
from django.test import Client, override_settings

from apps.chat.models import RateLimitLog


@pytest.mark.django_db
class TestSecurityHardening:
    def test_csrf_enforced_on_chat_and_riot_post_endpoints(self):
        csrf_client = Client(enforce_csrf_checks=True)

        r1 = csrf_client.post(
            "/chat/send/",
            data=json.dumps({"query": "Merhaba"}),
            content_type="application/json",
        )
        r2 = csrf_client.post(
            "/chat/stream/",
            data=json.dumps({"query": "Merhaba"}),
            content_type="application/json",
        )
        r3 = csrf_client.post(
            "/riot/player-matches/",
            data=json.dumps({"riot_id": "Test#TR1"}),
            content_type="application/json",
        )
        assert r1.status_code == 403
        assert r2.status_code == 403
        assert r3.status_code == 403

    @override_settings(RATELIMIT_LOGIN_PER_MIN=2)
    def test_login_rate_limit_blocks_brute_force_and_hashes_ip(self):
        client = Client()
        for _ in range(2):
            resp = client.post(
                "/accounts/login/",
                data=json.dumps({"username": "nobody", "password": "wrong"}),
                content_type="application/json",
            )
            assert resp.status_code in (400, 401)

        blocked = client.post(
            "/accounts/login/",
            data=json.dumps({"username": "nobody", "password": "wrong"}),
            content_type="application/json",
        )
        assert blocked.status_code == 429

        # Ensure raw IP is never stored in DB
        logs = list(RateLimitLog.objects.all())
        assert logs
        assert all("127.0.0.1" not in log.identifier for log in logs)

    @override_settings(RATELIMIT_PROMO_PER_MIN=2)
    def test_promo_redeem_rate_limit(self):
        user = User.objects.create_user(username="rl_promo_user", password="Password123!")
        client = Client()
        client.force_login(user)

        for _ in range(2):
            r = client.post(
                "/accounts/redeem-code/",
                data=json.dumps({"code": "INVALID"}),
                content_type="application/json",
            )
            assert r.status_code == 404

        blocked = client.post(
            "/accounts/redeem-code/",
            data=json.dumps({"code": "INVALID"}),
            content_type="application/json",
        )
        assert blocked.status_code == 429

    @override_settings(RATELIMIT_GUEST_DAILY=2)
    def test_guest_ip_daily_limit_prevents_cookie_reset_bypass(self):
        # Two separate fresh clients (simulating cookie clears from same IP)
        for _ in range(2):
            fresh = Client()
            r = fresh.post(
                "/chat/send/",
                data=json.dumps({"query": "Meta nedir?"}),
                content_type="application/json",
            )
            assert r.status_code == 200

        # 3rd fresh session from same IP must hit 429 even though session cookie is new
        third = Client()
        blocked = third.post(
            "/chat/send/",
            data=json.dumps({"query": "Cookie sildim tekrar soruyorum"}),
            content_type="application/json",
        )
        assert blocked.status_code == 429
        assert blocked.json().get("quota_exceeded") is True

    def test_health_endpoint_does_not_leak_exception_details(self):
        client = Client()
        with patch("apps.core.views.connection.cursor", side_effect=RuntimeError("SECRET_INTERNAL_PATH_/var/db")):
            resp = client.get("/health/")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "error"
        assert "SECRET_INTERNAL_PATH" not in body.get("detail", "")

    def test_pillow_decompression_bomb_limit_configured(self):
        import apps.chat.views  # noqa: F401
        assert Image.MAX_IMAGE_PIXELS == 25_000_000
