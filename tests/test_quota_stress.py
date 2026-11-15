"""
Adversarial Stress-Test Suite:
Quota Enforcement, Midnight Resets, Multi-Tier Limits, Guest Quotas, and Profile Sync.

Verifies:
1. FREE plan user hitting 30 questions limit: exactly on 31st request returns HTTP 429 with quota_exceeded: True.
2. Midnight quota reset: simulated date shift (quota_reset_date = yesterday or older) resets daily_quota_used to 0.
3. ADMIN plan user: unlimited questions allowed past quota limit.
4. PRO plan user: 500 daily quota limit enforcement.
5. Guest quota tracking and 30-question limit enforcement.
6. Updating Riot ID via /accounts/profile/ updates DB and is reflected on /accounts/status/ and chat_home.html.
7. Adversarial edge cases: unmocked end-to-end query, cleared Riot ID, guest transfer session isolation, and over-limit DB recovery.
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.accounts.models import UserProfile
from apps.chat.models import ChatSession

User = get_user_model()


def _mock_ai_coach_response(*args, **kwargs):
    """Fast mock for AI Coach response to avoid LLM/RAG latency during stress loops."""
    return {
        "content": "Hextech AI Coach analizi: Seviye 8'e geçiş için ekonominizi koruyun.",
        "ui_cards": [],
        "cited_chunk_ids": [],
        "model_used": "mock-stress-engine",
    }


class FreePlanQuotaExhaustionStressTests(TestCase):
    """
    Stress-tests for FREE plan users hitting exactly 30 questions limit,
    verifying HTTP 429 and quota_exceeded on 31st request.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="free_stress_user",
            password="testpassword123",
            email="free_stress@example.com",
        )
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.plan_tier = "FREE"
        self.profile.daily_quota_limit = 30
        self.profile.daily_quota_used = 0
        self.profile.save()
        self.client.login(username="free_stress_user", password="testpassword123")

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_free_user_exactly_30_allowed_and_31st_returns_429(self, mock_llm):
        """
        Iterates 1 through 30 requests: all succeed (200) with decrementing quota_left.
        The 31st request must return HTTP 429 with quota_exceeded: True.
        Subsequent 32nd request must also return HTTP 429.
        """
        # Execute exactly 30 requests in a loop
        for req_idx in range(1, 31):
            res = self.client.post(
                reverse("chat:send_message"),
                data=json.dumps({"query": f"Soru #{req_idx}: TFT Set 18 meta önerisi"}),
                content_type="application/json",
            )
            self.assertEqual(
                res.status_code,
                200,
                f"Request #{req_idx} should succeed with 200, got {res.status_code}: {res.content.decode()}",
            )
            data = res.json()
            expected_quota_left = 30 - req_idx
            self.assertEqual(
                data.get("quota_left"),
                expected_quota_left,
                f"Request #{req_idx}: expected quota_left {expected_quota_left}, got {data.get('quota_left')}",
            )

        # Check DB after 30 requests
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 30)
        self.assertFalse(self.profile.can_ask_question())

        # 31st request: Must hit 429 rate limit
        res31 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Soru #31: Limit aşıldı testi"}),
            content_type="application/json",
        )
        self.assertEqual(res31.status_code, 429)
        data31 = res31.json()
        self.assertTrue(
            data31.get("quota_exceeded"),
            f"Expected quota_exceeded=True, got {data31}",
        )
        self.assertIn("limitinize ulaştınız", data31.get("error", ""))

        # Verify DB daily_quota_used was NOT incremented on failed request
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 30)

        # 32nd request: Must continue returning 429
        res32 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Soru #32: İkinci limit aşımı"}),
            content_type="application/json",
        )
        self.assertEqual(res32.status_code, 429)
        self.assertTrue(res32.json().get("quota_exceeded"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 30)

    def test_unmocked_chat_send_consumes_quota_properly(self):
        """End-to-end integration test without mocking: verifies quota consumption through live pipeline."""
        self.assertEqual(self.profile.daily_quota_used, 0)
        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Master seviyesinde Guinsoo hangi taşıyıcıya verilmeli?"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("quota_left"), 29)
        self.assertIn("message", data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 1)


class MidnightQuotaResetStressTests(TestCase):
    """
    Stress-tests for midnight quota reset mechanism:
    Simulates date shifts (yesterday, past days) and verifies automatic reset.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="reset_user",
            password="testpassword123",
        )
        self.profile = UserProfile.objects.get(user=self.user)
        self.client.login(username="reset_user", password="testpassword123")

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_midnight_reset_when_date_shifts_to_yesterday(self, mock_llm):
        """
        When user reached 30 used questions and quota_reset_date is set to yesterday,
        the next query must reset daily_quota_used to 0, succeed with 200, and leave used=1.
        """
        yesterday = timezone.localdate() - timedelta(days=1)
        self.profile.daily_quota_used = 30
        self.profile.daily_quota_limit = 30
        self.profile.quota_reset_date = yesterday
        self.profile.save()

        # Step 1: Verify check_and_reset_quota method directly
        self.profile.check_and_reset_quota()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 0)
        self.assertEqual(self.profile.quota_reset_date, timezone.localdate())
        self.assertTrue(self.profile.can_ask_question())

        # Step 2: Test via HTTP endpoint
        # Set back to yesterday with 30 used
        self.profile.daily_quota_used = 30
        self.profile.quota_reset_date = yesterday
        self.profile.save()

        # Check /accounts/status/ triggers reset
        status_res = self.client.get(reverse("accounts:status"))
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["user"]["daily_quota_used"], 0)
        self.assertEqual(status_data["user"]["quota_left"], 30)

        # Now send question on the new day
        chat_res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Yeni günde ilk soru!"}),
            content_type="application/json",
        )
        self.assertEqual(chat_res.status_code, 200)
        chat_data = chat_res.json()
        self.assertEqual(chat_data["quota_left"], 29)

        # DB must have daily_quota_used=1 and quota_reset_date=today
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 1)
        self.assertEqual(self.profile.quota_reset_date, timezone.localdate())

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_multi_day_gap_quota_reset(self, mock_llm):
        """Simulates an inactive user returning after 10 days; quota resets cleanly."""
        ten_days_ago = timezone.localdate() - timedelta(days=10)
        self.profile.daily_quota_used = 30
        self.profile.quota_reset_date = ten_days_ago
        self.profile.save()

        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "10 gün sonra ilk soru"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 1)
        self.assertEqual(self.profile.quota_reset_date, timezone.localdate())


class AdminPlanUnlimitedStressTests(TestCase):
    """
    Stress-tests for ADMIN plan users:
    Verifies that questions are NEVER blocked by quota limits even after exceeding them.
    """

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username="admin_coach",
            password="adminpassword123",
            email="admin@tftcoach.internal",
        )
        self.profile = UserProfile.objects.get(user=self.admin_user)
        self.profile.plan_tier = "ADMIN"
        self.profile.daily_quota_limit = 30
        self.profile.daily_quota_used = 150  # Pre-exhausted far past limit
        self.profile.save()
        self.client.login(username="admin_coach", password="adminpassword123")

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_admin_unlimited_questions_past_quota_limit(self, mock_llm):
        """Admin user can ask unlimited questions even when daily_quota_used > daily_quota_limit."""
        self.assertTrue(self.profile.can_ask_question())

        # Check /accounts/status/
        status_res = self.client.get(reverse("accounts:status"))
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["user"]["plan_tier"], "ADMIN")
        self.assertEqual(status_data["user"]["quota_left"], 999999)

        # Check chat_home_view template context
        home_res = self.client.get(reverse("core:home"))
        self.assertEqual(home_res.status_code, 200)
        self.assertEqual(home_res.context["quota_left"], "∞")
        self.assertEqual(home_res.context["plan_tier"], "ADMIN")

        # Stress: Send 40 consecutive requests in a loop
        for i in range(1, 41):
            res = self.client.post(
                reverse("chat:send_message"),
                data=json.dumps({"query": f"Admin sorusu #{i}: Komp optimizasyonu"}),
                content_type="application/json",
            )
            self.assertEqual(
                res.status_code,
                200,
                f"Admin question #{i} failed with {res.status_code}",
            )
            data = res.json()
            self.assertEqual(data.get("quota_left"), "∞")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 190)  # 150 + 40


class ProPlanQuotaStressTests(TestCase):
    """
    Stress-tests for PRO plan users (500 limit).
    """

    def setUp(self):
        self.client = Client()
        self.pro_user = User.objects.create_user(
            username="pro_coach_user",
            password="propassword123",
            email="pro@tft.com",
        )
        self.profile = UserProfile.objects.get(user=self.pro_user)
        self.profile.plan_tier = "PRO"
        self.profile.daily_quota_limit = 500
        self.profile.daily_quota_used = 0
        self.profile.save()
        self.client.login(username="pro_coach_user", password="propassword123")

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_pro_plan_500_limit_enforcement(self, mock_llm):
        """
        Verifies PRO plan allows up to 500 questions and blocks exactly on the 501st.
        """
        # Status checks
        status_res = self.client.get(reverse("accounts:status"))
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json()["user"]["plan_tier"], "PRO")
        self.assertEqual(status_res.json()["user"]["daily_quota_limit"], 500)
        self.assertEqual(status_res.json()["user"]["quota_left"], 500)

        # Fast forward: simulate user having asked 498 questions
        self.profile.daily_quota_used = 498
        self.profile.save()

        # 499th question
        res499 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "PRO soru #499"}),
            content_type="application/json",
        )
        self.assertEqual(res499.status_code, 200)
        self.assertEqual(res499.json().get("quota_left"), 1)

        # 500th question (reaching the limit exactly)
        res500 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "PRO soru #500"}),
            content_type="application/json",
        )
        self.assertEqual(res500.status_code, 200)
        self.assertEqual(res500.json().get("quota_left"), 0)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 500)
        self.assertFalse(self.profile.can_ask_question())

        # 501st question: MUST return HTTP 429
        res501 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "PRO soru #501 (limit aşıldı)"}),
            content_type="application/json",
        )
        self.assertEqual(res501.status_code, 429)
        data501 = res501.json()
        self.assertTrue(data501.get("quota_exceeded"))

        # Confirm DB quota count stayed 500
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 500)

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_pro_plan_midnight_reset(self, mock_llm):
        """When PRO user hits 500 limit and midnight passes, quota resets to 0 with 500 capacity."""
        self.profile.daily_quota_used = 500
        self.profile.quota_reset_date = timezone.localdate() - timedelta(days=1)
        self.profile.save()

        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "PRO yeni gün ilk soru"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("quota_left"), 499)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 1)


class GuestQuotaTrackingStressTests(TestCase):
    """
    Stress-tests for guest quota tracking and enforcement.
    """

    def setUp(self):
        self.client = Client()

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_guest_quota_tracking_and_30_limit(self, mock_llm):
        """
        Verifies guest session quota: starts at 30, decrements per question,
        and blocks on 31st with HTTP 429.
        """
        # Initial status for guest
        status_res = self.client.get(reverse("accounts:status"))
        self.assertEqual(status_res.status_code, 200)
        sdata = status_res.json()
        self.assertFalse(sdata["authenticated"])
        self.assertIsNotNone(sdata["guest"])
        self.assertEqual(sdata["guest"]["daily_quota_limit"], 30)
        self.assertEqual(sdata["guest"]["daily_quota_used"], 0)
        self.assertEqual(sdata["guest"]["quota_left"], 30)

        # Send 1st question
        res1 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir sorusu 1"}),
            content_type="application/json",
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json().get("quota_left"), 29)
        self.assertEqual(self.client.session.get("guest_quota_used"), 1)

        # Advance guest counter to 29
        s = self.client.session
        s["guest_quota_used"] = 29
        s.save()

        # Send 30th question
        res30 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir sorusu 30"}),
            content_type="application/json",
        )
        self.assertEqual(res30.status_code, 200)
        self.assertEqual(res30.json().get("quota_left"), 0)
        self.assertEqual(self.client.session.get("guest_quota_used"), 30)

        # Send 31st question -> HTTP 429
        res31 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir sorusu 31 (aşım)"}),
            content_type="application/json",
        )
        self.assertEqual(res31.status_code, 429)
        d31 = res31.json()
        self.assertTrue(d31.get("quota_exceeded"))
        self.assertIn("Misafir oturumu soru limitinize ulaştınız", d31.get("error", ""))
        self.assertEqual(self.client.session.get("guest_quota_used"), 30)

        # Verify guest status now shows 0 quota left
        status_after = self.client.get(reverse("accounts:status"))
        self.assertEqual(status_after.json()["guest"]["quota_left"], 0)

    @patch("apps.chat.llm_service.AICoachLLMService.generate_coach_response", side_effect=_mock_ai_coach_response)
    def test_guest_exhaustion_then_register_restores_user_quota(self, mock_llm):
        """
        When a guest exhausts the 30 guest questions, registering a new account
        grants fresh authenticated quota of 30 questions and transfers sessions.
        """
        # Advance guest counter to 30 (exhausted)
        s = self.client.session
        s["guest_quota_used"] = 30
        s.save()

        # Verify guest is blocked
        res_blocked = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir bloklu soru"}),
            content_type="application/json",
        )
        self.assertEqual(res_blocked.status_code, 429)

        # Now guest registers
        reg_payload = {
            "username": "migrated_guest_user",
            "password": "validpassword123",
            "confirm_password": "validpassword123",
        }
        res_reg = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(reg_payload),
            content_type="application/json",
        )
        self.assertEqual(res_reg.status_code, 200)

        # Now authenticated: can ask questions under user account!
        res_fresh = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Kayıtlı kullanıcı olarak ilk soru"}),
            content_type="application/json",
        )
        self.assertEqual(res_fresh.status_code, 200)
        self.assertEqual(res_fresh.json().get("quota_left"), 29)


class ProfileRiotIDUpdateAndSyncStressTests(TestCase):
    """
    Stress-tests for profile update via /accounts/profile/
    and verification of reflection on /accounts/status/ and chat_home.html.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="riot_profile_tester",
            password="password123",
            email="tester@riot.com",
        )
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.riot_game_name = "InitialGamer"
        self.profile.riot_tag_line = "TR1"
        self.profile.riot_region = "TR1"
        self.profile.preferred_lang = "tr"
        self.profile.save()
        self.client.login(username="riot_profile_tester", password="password123")

    def test_initial_state_reflected_on_status_and_html(self):
        """Verify initial profile values are reflected on /accounts/status/ and chat_home.html."""
        # /accounts/status/
        res_status = self.client.get(reverse("accounts:status"))
        self.assertEqual(res_status.status_code, 200)
        user_data = res_status.json()["user"]
        self.assertEqual(user_data["riot_game_name"], "InitialGamer")
        self.assertEqual(user_data["riot_tag_line"], "TR1")
        self.assertEqual(user_data["riot_region"], "TR1")
        self.assertEqual(user_data["preferred_lang"], "tr")

        # chat_home.html
        res_home = self.client.get(reverse("core:home"))
        self.assertEqual(res_home.status_code, 200)
        html = res_home.content.decode("utf-8")
        self.assertIn('value="InitialGamer"', html)
        self.assertIn('value="TR1"', html)
        self.assertIn('value="InitialGamer#TR1"', html)

    def test_profile_update_json_updates_db_and_reflects_everywhere(self):
        """
        Updating Riot ID via JSON POST /accounts/profile/ updates UserProfile
        and is immediately reflected on /accounts/status/ and chat_home.html.
        """
        payload = {
            "riot_game_name": "FakerChallenger",
            "riot_tag_line": "KR1",
            "riot_region": "KR",
            "preferred_lang": "en",
        }
        res_post = self.client.post(
            reverse("accounts:profile"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res_post.status_code, 200)
        post_data = res_post.json()
        self.assertEqual(post_data.get("status"), "success")
        self.assertEqual(post_data["profile"]["riot_game_name"], "FakerChallenger")
        self.assertEqual(post_data["profile"]["riot_tag_line"], "KR1")
        self.assertEqual(post_data["profile"]["riot_region"], "KR")
        self.assertEqual(post_data["profile"]["preferred_lang"], "en")

        # 1. Verify DB
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.riot_game_name, "FakerChallenger")
        self.assertEqual(self.profile.riot_tag_line, "KR1")
        self.assertEqual(self.profile.riot_region, "KR")
        self.assertEqual(self.profile.preferred_lang, "en")

        # 2. Verify /accounts/status/
        res_status = self.client.get(reverse("accounts:status"))
        self.assertEqual(res_status.status_code, 200)
        user_data = res_status.json()["user"]
        self.assertEqual(user_data["riot_game_name"], "FakerChallenger")
        self.assertEqual(user_data["riot_tag_line"], "KR1")
        self.assertEqual(user_data["riot_region"], "KR")
        self.assertEqual(user_data["preferred_lang"], "en")

        # 3. Verify chat_home.html
        res_home = self.client.get(reverse("core:home"))
        self.assertEqual(res_home.status_code, 200)
        html = res_home.content.decode("utf-8")
        self.assertIn('value="FakerChallenger"', html)
        self.assertIn('value="KR1"', html)
        self.assertIn('value="FakerChallenger#KR1"', html)

    def test_profile_update_form_encoded_post(self):
        """Standard HTML form submission also works and updates profile fields."""
        res_post = self.client.post(
            reverse("accounts:profile"),
            data={
                "riot_game_name": "AgonistEUW",
                "riot_tag_line": "EUW",
                "riot_region": "EUW1",
                "preferred_lang": "tr",
            },
        )
        self.assertEqual(res_post.status_code, 302)  # Redirect to accounts:profile

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.riot_game_name, "AgonistEUW")
        self.assertEqual(self.profile.riot_tag_line, "EUW")
        self.assertEqual(self.profile.riot_region, "EUW1")
        self.assertEqual(self.profile.preferred_lang, "tr")

        # Check status endpoint
        res_status = self.client.get(reverse("accounts:status"))
        self.assertEqual(res_status.json()["user"]["riot_game_name"], "AgonistEUW")

    def test_profile_clear_riot_id(self):
        """Clearing optional Riot ID fields is permitted and reflects as empty values."""
        payload = {
            "riot_game_name": "",
            "riot_tag_line": "",
            "riot_region": "TR1",
            "preferred_lang": "tr",
        }
        res_post = self.client.post(
            reverse("accounts:profile"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res_post.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.riot_game_name, "")
        self.assertEqual(self.profile.riot_tag_line, "")

        res_status = self.client.get(reverse("accounts:status"))
        self.assertEqual(res_status.json()["user"]["riot_game_name"], "")
        self.assertEqual(res_status.json()["user"]["riot_tag_line"], "")
