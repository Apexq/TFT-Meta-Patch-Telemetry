"""
Comprehensive tests for User Accounts, Guest Chat Transfer, and Daily Quota System.
"""

import json
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.accounts.models import UserProfile
from apps.chat.models import ChatSession

User = get_user_model()


class AccountsRegistrationTests(TestCase):
    """Tests for user registration endpoints and forms."""

    def setUp(self):
        self.client = Client()

    def test_registration_page_get(self):
        """GET /accounts/register/ returns 200 with registration form."""
        res = self.client.get(reverse("accounts:register"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Ücretsiz Hesap Oluştur")

    def test_registration_success_json(self):
        """Valid JSON registration creates User, UserProfile and logs in."""
        payload = {
            "username": "tft_player_1",
            "email": "player1@example.com",
            "password": "securepassword123",
            "confirm_password": "securepassword123",
            "riot_game_name": "Agonist",
            "riot_tag_line": "TR1",
            "riot_region": "TR1",
        }
        res = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["username"], "tft_player_1")

        # Verify DB
        user = User.objects.filter(username="tft_player_1").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "player1@example.com")
        self.assertTrue(user.check_password("securepassword123"))

        # Verify profile created and populated
        profile = getattr(user, "profile", None)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.riot_game_name, "Agonist")
        self.assertEqual(profile.riot_tag_line, "TR1")
        self.assertEqual(profile.riot_region, "TR1")
        self.assertEqual(profile.plan_tier, "FREE")
        self.assertEqual(profile.daily_quota_limit, 30)
        self.assertEqual(profile.daily_quota_used, 0)

        # Verify user is logged in
        status_res = self.client.get(reverse("accounts:status"))
        self.assertEqual(status_res.status_code, 200)
        self.assertTrue(status_res.json()["authenticated"])

    def test_registration_password_mismatch(self):
        """Registration fails when password and confirm_password do not match."""
        payload = {
            "username": "mismatch_user",
            "password": "passwordA123",
            "confirm_password": "passwordB456",
        }
        res = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("confirm_password", data["errors"])
        self.assertFalse(User.objects.filter(username="mismatch_user").exists())

    def test_registration_password_too_short(self):
        """Registration fails when password is less than 6 characters."""
        payload = {
            "username": "short_pw_user",
            "password": "123",
            "confirm_password": "123",
        }
        res = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(User.objects.filter(username="short_pw_user").exists())

    def test_registration_duplicate_username(self):
        """Registration fails if username is already taken."""
        User.objects.create_user(username="existing_player", password="password123")
        payload = {
            "username": "existing_player",
            "password": "newpassword123",
            "confirm_password": "newpassword123",
        }
        res = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertIn("username", data["errors"])

    def test_registration_html_form_post(self):
        """Registration works via standard HTML form-encoded POST."""
        res = self.client.post(
            reverse("accounts:register"),
            data={
                "username": "form_player",
                "email": "form@example.com",
                "password": "formpassword123",
                "confirm_password": "formpassword123",
                "riot_game_name": "FormHero",
                "riot_tag_line": "EUW",
                "riot_region": "EUW1",
            },
        )
        self.assertEqual(res.status_code, 302)  # Redirects to "/"
        self.assertTrue(User.objects.filter(username="form_player").exists())


class AccountsLoginLogoutTests(TestCase):
    """Tests for user login, authentication verification, and logout."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="auth_user",
            email="auth@example.com",
            password="correctpassword123",
        )

    def test_login_page_get(self):
        """GET /accounts/login/ renders login page."""
        res = self.client.get(reverse("accounts:login"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Giriş Yap")

    def test_login_success_json(self):
        """POST /accounts/login/ with valid credentials authenticates user."""
        res = self.client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "auth_user", "password": "correctpassword123"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["username"], "auth_user")

        # Verify session is authenticated
        status_res = self.client.get(reverse("accounts:status"))
        self.assertTrue(status_res.json()["authenticated"])
        self.assertEqual(status_res.json()["user"]["username"], "auth_user")

    def test_login_invalid_credentials_json(self):
        """POST /accounts/login/ with wrong password returns 400."""
        res = self.client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "auth_user", "password": "wrongpassword"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data["status"], "error")

    def test_login_nonexistent_user(self):
        """POST /accounts/login/ with nonexistent username returns 400."""
        res = self.client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "nobody_here", "password": "anypassword"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

    def test_logout(self):
        """Logging out clears session and status becomes unauthenticated."""
        self.client.login(username="auth_user", password="correctpassword123")
        status_res = self.client.get(reverse("accounts:status"))
        self.assertTrue(status_res.json()["authenticated"])

        logout_res = self.client.post(reverse("accounts:logout"))
        self.assertIn(logout_res.status_code, [200, 302])

        status_after = self.client.get(reverse("accounts:status"))
        self.assertFalse(status_after.json()["authenticated"])


class GuestChatTransferTests(TestCase):
    """
    Tests for guest session transfer upon user login/registration.
    Ensures pre-login guest session key is captured before session key cycling.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="transfer_user",
            password="userpassword123",
        )

    def test_guest_session_transfer_on_login(self):
        """
        Anonymous guest creates 2 chat sessions with a session key.
        Upon logging in, both sessions have user set to the logged-in user
        and guest_session_key set to empty string.
        """
        # 1. Establish guest session
        self.client.get(reverse("core:home"))
        guest_key = self.client.session.session_key
        self.assertTrue(bool(guest_key), "Session key should be established")

        # 2. Create guest chat sessions
        sess1 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Misafir Sohbet 1 - LeBlanc",
        )
        sess2 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Misafir Sohbet 2 - Guinsoo",
        )
        other_guest_sess = ChatSession.objects.create(
            guest_session_key="other_random_guest_key",
            title="Başka Misafir Sohbeti",
        )

        # 3. Log in through /accounts/login/
        login_res = self.client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "transfer_user", "password": "userpassword123"}),
            content_type="application/json",
        )
        self.assertEqual(login_res.status_code, 200)

        # 4. Verify sessions transferred
        sess1.refresh_from_db()
        sess2.refresh_from_db()
        other_guest_sess.refresh_from_db()

        self.assertEqual(sess1.user, self.user)
        self.assertEqual(sess1.guest_session_key, "")
        self.assertEqual(sess2.user, self.user)
        self.assertEqual(sess2.guest_session_key, "")

        # Other guest session remains untouched
        self.assertIsNone(other_guest_sess.user)
        self.assertEqual(other_guest_sess.guest_session_key, "other_random_guest_key")

    def test_guest_session_transfer_on_registration(self):
        """
        Anonymous guest creates a chat session, then registers.
        The session is transferred to the newly registered user.
        """
        self.client.get(reverse("core:home"))
        guest_key = self.client.session.session_key
        sess = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Pre-reg Guest Chat",
        )

        reg_res = self.client.post(
            reverse("accounts:register"),
            data=json.dumps({
                "username": "newly_registered_user",
                "password": "somepassword123",
                "confirm_password": "somepassword123",
            }),
            content_type="application/json",
        )
        self.assertEqual(reg_res.status_code, 200)

        new_user = User.objects.get(username="newly_registered_user")
        sess.refresh_from_db()
        self.assertEqual(sess.user, new_user)
        self.assertEqual(sess.guest_session_key, "")


class ProfileManagementTests(TestCase):
    """Tests for viewing and updating user profile and Riot ID."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="profile_player",
            password="playerpassword123",
            email="player@tft.com",
        )
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.riot_game_name = "InitialName"
        self.profile.riot_tag_line = "TR1"
        self.profile.save()

    def test_profile_unauthenticated_returns_401_or_redirect(self):
        """Unauthenticated access to profile view is protected."""
        res_json = self.client.get(reverse("accounts:profile"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res_json.status_code, 401)

        res_html = self.client.get(reverse("accounts:profile"))
        self.assertEqual(res_html.status_code, 302)

    def test_profile_get_json(self):
        """Authenticated GET returns user profile details."""
        self.client.login(username="profile_player", password="playerpassword123")
        res = self.client.get(reverse("accounts:profile"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["username"], "profile_player")
        self.assertEqual(data["riot_game_name"], "InitialName")
        self.assertEqual(data["riot_tag_line"], "TR1")
        self.assertEqual(data["plan_tier"], "FREE")
        self.assertEqual(data["daily_quota_limit"], 30)

    def test_profile_update_post_json(self):
        """Authenticated POST updates Riot ID fields and preferred language."""
        self.client.login(username="profile_player", password="playerpassword123")
        payload = {
            "riot_game_name": "UpdatedChallenger",
            "riot_tag_line": "EUW",
            "riot_region": "EUW1",
            "preferred_lang": "en",
        }
        res = self.client.post(
            reverse("accounts:profile"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["profile"]["riot_game_name"], "UpdatedChallenger")
        self.assertEqual(data["profile"]["riot_tag_line"], "EUW")
        self.assertEqual(data["profile"]["riot_region"], "EUW1")
        self.assertEqual(data["profile"]["preferred_lang"], "en")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.riot_game_name, "UpdatedChallenger")
        self.assertEqual(self.profile.riot_tag_line, "EUW")
        self.assertEqual(self.profile.riot_region, "EUW1")
        self.assertEqual(self.profile.preferred_lang, "en")

    def test_profile_status_authenticated_vs_guest(self):
        """GET /accounts/status/ distinguishes authenticated users and guests."""
        # 1. Guest
        res_guest = self.client.get(reverse("accounts:status"))
        self.assertEqual(res_guest.status_code, 200)
        data_guest = res_guest.json()
        self.assertFalse(data_guest["authenticated"])
        self.assertIsNone(data_guest["user"])
        self.assertIn("guest", data_guest)
        self.assertEqual(data_guest["guest"]["daily_quota_limit"], 30)

        # 2. Authenticated
        self.client.login(username="profile_player", password="playerpassword123")
        res_auth = self.client.get(reverse("accounts:status"))
        self.assertEqual(res_auth.status_code, 200)
        data_auth = res_auth.json()
        self.assertTrue(data_auth["authenticated"])
        self.assertIsNotNone(data_auth["user"])
        self.assertEqual(data_auth["user"]["username"], "profile_player")
        self.assertEqual(data_auth["user"]["plan_tier"], "FREE")


class QuotaSystemTests(TestCase):
    """
    Tests for quota consumption, exhaustion (HTTP 429),
    daily reset mechanism, and admin bypass.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="quota_user",
            password="quota_pass_123",
        )
        self.profile = UserProfile.objects.get(user=self.user)

    def test_quota_consumption_on_chat_send(self):
        """Each valid chat query decrements remaining quota and increments daily_quota_used."""
        self.client.login(username="quota_user", password="quota_pass_123")
        self.assertEqual(self.profile.daily_quota_used, 0)

        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Guinsoo ile ne gider?"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["quota_left"], 29)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 1)

    def test_quota_exhaustion_returns_429(self):
        """When daily quota limit is reached, send_message returns HTTP 429."""
        self.client.login(username="quota_user", password="quota_pass_123")
        self.profile.daily_quota_used = 30
        self.profile.daily_quota_limit = 30
        self.profile.save(update_fields=["daily_quota_used", "daily_quota_limit"])

        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Limit doluyken bu soru sorulamaz"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 429)
        data = res.json()
        self.assertTrue(data.get("quota_exceeded"))
        self.assertIn("Günlük soru limitinize ulaştınız", data.get("error", ""))

    def test_daily_quota_reset_logic(self):
        """
        When quota_reset_date is in the past, user quota is reset to 0
        and quota_reset_date is updated to today.
        """
        yesterday = timezone.localdate() - timedelta(days=1)
        self.profile.quota_reset_date = yesterday
        self.profile.daily_quota_used = 30
        self.profile.save(update_fields=["quota_reset_date", "daily_quota_used"])

        # Directly testing UserProfile method
        self.assertTrue(self.profile.can_ask_question())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 0)
        self.assertEqual(self.profile.quota_reset_date, timezone.localdate())

        # Test via HTTP endpoint
        self.profile.quota_reset_date = yesterday
        self.profile.daily_quota_used = 30
        self.profile.save(update_fields=["quota_reset_date", "daily_quota_used"])

        self.client.login(username="quota_user", password="quota_pass_123")
        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Yeni günde ilk soru"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_used, 1)
        self.assertEqual(self.profile.quota_reset_date, timezone.localdate())

    def test_admin_plan_bypasses_quota_limit(self):
        """User with plan_tier='ADMIN' can ask unlimited questions even if used > limit."""
        self.profile.plan_tier = "ADMIN"
        self.profile.daily_quota_used = 100
        self.profile.daily_quota_limit = 30
        self.profile.save(update_fields=["plan_tier", "daily_quota_used", "daily_quota_limit"])

        self.client.login(username="quota_user", password="quota_pass_123")
        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Admin sınırsız soru"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["quota_left"], "∞")

    def test_guest_quota_enforcement(self):
        """Guest sessions track question count in session and hit 429 at limit."""
        # 1. First question as guest works and increments counter
        res1 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir sorusu #1"}),
            content_type="application/json",
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(self.client.session.get("guest_quota_used"), 1)

        # 2. Advance guest quota counter to 29 in session
        s = self.client.session
        s["guest_quota_used"] = 29
        s.save()

        # 3. 30th question reaches limit
        res30 = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir sorusu #30"}),
            content_type="application/json",
        )
        self.assertEqual(res30.status_code, 200)
        self.assertEqual(self.client.session.get("guest_quota_used"), 30)

        # 4. 31st question fails with 429
        res_limit = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "Misafir sorusu #31 (limit aşıldı)"}),
            content_type="application/json",
        )
        self.assertEqual(res_limit.status_code, 429)
        data = res_limit.json()
        self.assertTrue(data.get("quota_exceeded"))
        self.assertIn("Misafir oturumu soru limitinize ulaştınız", data.get("error", ""))

    def test_login_open_redirect_blocked_and_logout_post_only(self):
        """
        Ensures login rejects external/scheme-relative next URLs (Open Redirect)
        and logout rejects GET requests with 405 Method Not Allowed.
        """
        User.objects.create_user(username="redir_user", password="password123")

        res_evil = self.client.post(
            reverse("accounts:login") + "?next=https://evil.example.com/phish",
            data={"username": "redir_user", "password": "password123"},
        )
        self.assertEqual(res_evil.status_code, 302)
        self.assertEqual(res_evil.url, "/")

        res_get_logout = self.client.get(reverse("accounts:logout"))
        self.assertEqual(res_get_logout.status_code, 405)

        # GET logout must not have logged user out; verify safe internal redirect on a fresh unauthenticated client
        fresh_client = Client()
        res_safe = fresh_client.post(
            reverse("accounts:login") + "?next=/accounts/profile/",
            data={"username": "redir_user", "password": "password123"},
        )
        self.assertEqual(res_safe.status_code, 302)
        self.assertEqual(res_safe.url, "/accounts/profile/")

    def test_pro_plan_dynamic_quota_sync_and_429_message(self):
        """
        Switching plan_tier from FREE to PRO updates daily_quota_limit to 500
        and the 429 message dynamically reports 500 soru/gün.
        """
        self.profile.plan_tier = "PRO"
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_quota_limit, 500)

        self.profile.daily_quota_used = 500
        self.profile.save(update_fields=["daily_quota_used"])

        self.client.login(username="quota_user", password="quota_pass_123")
        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({"query": "PRO limit check"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 429)
        self.assertIn("500 soru/gün", res.json().get("error", ""))
