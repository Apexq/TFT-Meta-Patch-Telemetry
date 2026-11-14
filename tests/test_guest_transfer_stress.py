"""
Empirical stress-test suite for Milestone 3 (Task 7): Guest Chat Transfer & Auth Flows.
Challenger Verification Harness for adversarial testing and edge case exploration.
"""

import json
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.chat.models import ChatSession, ChatMessage
from apps.accounts.models import UserProfile

User = get_user_model()


class GuestChatTransferStressTests(TestCase):
    """
    Stress-testing guest chat session migration, multi-session transfers,
    cross-user isolation, standard vs AJAX auth, zero-message edge cases,
    and missing cookie handling.
    """

    def setUp(self):
        self.user_a = User.objects.create_user(
            username="challenger_user_a",
            password="StrongPassword123!",
            email="user_a@tftcoach.ai",
        )
        self.user_b = User.objects.create_user(
            username="challenger_user_b",
            password="StrongPassword456!",
            email="user_b@tftcoach.ai",
        )

    def test_01_multiple_guest_sessions_migration_standard_form_login(self):
        """
        Create 10 guest sessions under a single guest session key.
        Log in via standard HTTP form submission (x-www-form-urlencoded).
        Verify ALL 10 sessions migrate to user_a and guest_session_key is cleared.
        Verify User B's sessions are completely untouched.
        """
        # User B has pre-existing sessions
        user_b_sess1 = ChatSession.objects.create(
            user=self.user_b,
            guest_session_key="",
            title="User B Session 1",
        )
        user_b_sess2 = ChatSession.objects.create(
            user=self.user_b,
            guest_session_key="",
            title="User B Session 2",
        )

        client = Client()
        # Establish guest session
        home_res = client.get(reverse("core:home"))
        self.assertEqual(home_res.status_code, 200)
        guest_key = client.session.session_key
        self.assertTrue(bool(guest_key), "Guest session key must be established")

        # Create 10 diverse guest sessions
        created_sessions = []
        for i in range(10):
            sess = ChatSession.objects.create(
                guest_session_key=guest_key,
                title=f"Guest Test Session {i}",
                mode="META_COACH" if i % 2 == 0 else "OPENER_BUILDER",
            )
            # Some with messages, some with 0 messages
            if i % 3 != 0:
                ChatMessage.objects.create(
                    session=sess,
                    role="user",
                    content_markdown=f"Question in session {i}",
                )
                ChatMessage.objects.create(
                    session=sess,
                    role="assistant",
                    content_markdown=f"Answer in session {i}",
                )
            created_sessions.append(sess)

        # Standard form login (redirects to / or next)
        login_res = client.post(
            reverse("accounts:login"),
            data={"username": "challenger_user_a", "password": "StrongPassword123!"},
        )
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res.url, "/")

        # Verify all 10 guest sessions migrated to User A
        for sess in created_sessions:
            sess.refresh_from_db()
            self.assertEqual(sess.user, self.user_a)
            self.assertEqual(sess.guest_session_key, "")

        # Verify User B's sessions untouched
        user_b_sess1.refresh_from_db()
        user_b_sess2.refresh_from_db()
        self.assertEqual(user_b_sess1.user, self.user_b)
        self.assertEqual(user_b_sess2.user, self.user_b)

        # Verify User A now owns exactly 10 sessions
        self.assertEqual(ChatSession.objects.filter(user=self.user_a).count(), 10)
        # Verify 0 sessions remain under the old guest key
        self.assertEqual(ChatSession.objects.filter(guest_session_key=guest_key).count(), 0)

    def test_02_multiple_guest_sessions_migration_ajax_json_login(self):
        """
        Create 5 guest sessions under a guest session key.
        Log in via AJAX JSON modal submission.
        Verify HTTP 200 JSON response and all sessions migrated.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        sessions = [
            ChatSession.objects.create(
                guest_session_key=guest_key,
                title=f"AJAX Modal Guest Session {i}",
            )
            for i in range(5)
        ]

        # AJAX modal login
        login_res = client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(login_res.status_code, 200)
        resp_data = login_res.json()
        self.assertEqual(resp_data.get("status"), "success")
        self.assertEqual(resp_data.get("username"), "challenger_user_a")

        for sess in sessions:
            sess.refresh_from_db()
            self.assertEqual(sess.user, self.user_a)
            self.assertEqual(sess.guest_session_key, "")

        self.assertEqual(ChatSession.objects.filter(user=self.user_a).count(), 5)

    def test_03_registration_with_auto_login_standard_form_migration(self):
        """
        Guest creates sessions and registers via standard HTTP form submission.
        Auto-login must trigger session migration to the newly registered user.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        sess1 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Pre-reg Form Session 1",
        )
        sess2 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Pre-reg Form Session 2",
        )

        reg_payload = {
            "username": "new_form_user",
            "email": "newform@tftcoach.ai",
            "password": "SafePassword789!",
            "confirm_password": "SafePassword789!",
            "riot_game_name": "TFTMaster",
            "riot_tag_line": "EUW",
            "riot_region": "EUW1",
        }
        res = client.post(reverse("accounts:register"), data=reg_payload)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, "/")

        new_user = User.objects.filter(username="new_form_user").first()
        self.assertIsNotNone(new_user)

        sess1.refresh_from_db()
        sess2.refresh_from_db()
        self.assertEqual(sess1.user, new_user)
        self.assertEqual(sess1.guest_session_key, "")
        self.assertEqual(sess2.user, new_user)
        self.assertEqual(sess2.guest_session_key, "")

    def test_04_registration_with_auto_login_ajax_json_migration(self):
        """
        Guest creates sessions and registers via AJAX JSON modal submission.
        Auto-login must trigger session migration.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        sess = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Pre-reg JSON Modal Session",
        )

        reg_payload = {
            "username": "new_json_user",
            "email": "newjson@tftcoach.ai",
            "password": "SafePassword789!",
            "confirm_password": "SafePassword789!",
        }
        res = client.post(
            reverse("accounts:register"),
            data=json.dumps(reg_payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "success")

        new_user = User.objects.get(username="new_json_user")
        sess.refresh_from_db()
        self.assertEqual(sess.user, new_user)
        self.assertEqual(sess.guest_session_key, "")

    def test_05_preexisting_sessions_of_another_user_never_transferred(self):
        """
        Adversarial test: Even if a pre-existing session belonging to User B has a
        guest_session_key set to the current guest's session key (e.g. simulated collision),
        it must NEVER be transferred to User A because user is already set.
        Also verifies unrelated guest sessions are untouched.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        # Legitimate guest session for current visitor
        guest_sess = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Legitimate Guest Session",
        )

        # Adversarial scenario: User B session with collision
        user_b_collision_sess = ChatSession.objects.create(
            user=self.user_b,
            guest_session_key=guest_key,  # Simulated collision or stale key
            title="User B Session With Stale Key",
        )

        # Unrelated third guest session
        unrelated_guest_sess = ChatSession.objects.create(
            guest_session_key="unrelated_guest_session_9999",
            title="Unrelated Guest Session",
        )

        # Log in as User A
        client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )

        guest_sess.refresh_from_db()
        user_b_collision_sess.refresh_from_db()
        unrelated_guest_sess.refresh_from_db()

        # Legitimate guest session migrated to User A
        self.assertEqual(guest_sess.user, self.user_a)
        self.assertEqual(guest_sess.guest_session_key, "")

        # User B's session remained strictly User B's property
        self.assertEqual(user_b_collision_sess.user, self.user_b)

        # Unrelated guest session remained unowned
        self.assertIsNone(unrelated_guest_sess.user)
        self.assertEqual(unrelated_guest_sess.guest_session_key, "unrelated_guest_session_9999")

    def test_06_login_without_preexisting_cookies_or_sessions_no_crash(self):
        """
        Verify that logging in with a clean client (no cookie, no session key)
        does not raise KeyError, AttributeError, or 500 error.
        """
        fresh_client = Client()
        # Do not visit any page before login — no cookies exist
        res = fresh_client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "success")

        # Verify user is logged in
        status_res = fresh_client.get(reverse("accounts:status"))
        self.assertEqual(status_res.status_code, 200)
        self.assertTrue(status_res.json()["authenticated"])

    def test_07_guest_sessions_with_zero_messages_migrate_cleanly(self):
        """
        Verify guest sessions with 0 messages migrate cleanly without ORM errors.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        empty_sess1 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Empty Guest Session 1",
        )
        empty_sess2 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Empty Guest Session 2",
        )
        self.assertEqual(empty_sess1.messages.count(), 0)
        self.assertEqual(empty_sess2.messages.count(), 0)

        res = client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        empty_sess1.refresh_from_db()
        empty_sess2.refresh_from_db()
        self.assertEqual(empty_sess1.user, self.user_a)
        self.assertEqual(empty_sess1.guest_session_key, "")
        self.assertEqual(empty_sess1.messages.count(), 0)

        self.assertEqual(empty_sess2.user, self.user_a)
        self.assertEqual(empty_sess2.guest_session_key, "")
        self.assertEqual(empty_sess2.messages.count(), 0)

    def test_08_failed_login_and_failed_registration_never_migrate_sessions(self):
        """
        Adversarial test: If a user enters invalid credentials or bad registration data,
        guest sessions must NEVER be transferred prematurely.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        guest_sess = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Session During Failed Attempts",
        )

        # 1. Failed login with wrong password
        failed_login = client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "WrongPassword!"}),
            content_type="application/json",
        )
        self.assertEqual(failed_login.status_code, 400)
        guest_sess.refresh_from_db()
        self.assertIsNone(guest_sess.user)
        self.assertEqual(guest_sess.guest_session_key, guest_key)

        # 2. Failed registration with password mismatch
        failed_reg = client.post(
            reverse("accounts:register"),
            data=json.dumps({
                "username": "failed_reg_user",
                "password": "Password123!",
                "confirm_password": "DifferentPassword456!",
            }),
            content_type="application/json",
        )
        self.assertEqual(failed_reg.status_code, 400)
        guest_sess.refresh_from_db()
        self.assertIsNone(guest_sess.user)
        self.assertEqual(guest_sess.guest_session_key, guest_key)

        # 3. Successful login now succeeds and migrates
        success_login = client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(success_login.status_code, 200)
        guest_sess.refresh_from_db()
        self.assertEqual(guest_sess.user, self.user_a)
        self.assertEqual(guest_sess.guest_session_key, "")

    def test_09_user_with_existing_sessions_merges_properly(self):
        """
        User A already has 2 historical sessions.
        Logs out, creates 2 new guest sessions, logs back in.
        User A must now have 4 sessions (2 historical + 2 migrated).
        """
        # User A's historical sessions
        hist1 = ChatSession.objects.create(
            user=self.user_a,
            guest_session_key="",
            title="User A Historical 1",
        )
        hist2 = ChatSession.objects.create(
            user=self.user_a,
            guest_session_key="",
            title="User A Historical 2",
        )

        # New guest session
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        new_guest1 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="New Guest Session 1",
        )
        new_guest2 = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="New Guest Session 2",
        )

        # Log in
        client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )

        user_a_sessions = list(ChatSession.objects.filter(user=self.user_a))
        self.assertEqual(len(user_a_sessions), 4)

        session_ids = {s.id for s in user_a_sessions}
        self.assertIn(hist1.id, session_ids)
        self.assertIn(hist2.id, session_ids)
        self.assertIn(new_guest1.id, session_ids)
        self.assertIn(new_guest2.id, session_ids)

    def test_10_concurrent_guest_isolation_and_sequential_login(self):
        """
        Two separate guests browse concurrently:
        Guest 1 creates 3 sessions. Guest 2 creates 3 sessions.
        Guest 1 logs in -> only Guest 1's sessions transferred to User A.
        Guest 2 logs in -> only Guest 2's sessions transferred to User B.
        Zero crosstalk.
        """
        client1 = Client()
        client1.get(reverse("core:home"))
        key1 = client1.session.session_key

        client2 = Client()
        client2.get(reverse("core:home"))
        key2 = client2.session.session_key

        self.assertNotEqual(key1, key2)

        sessions_client1 = [
            ChatSession.objects.create(guest_session_key=key1, title=f"C1 Sess {i}")
            for i in range(3)
        ]
        sessions_client2 = [
            ChatSession.objects.create(guest_session_key=key2, title=f"C2 Sess {i}")
            for i in range(3)
        ]

        # Client 1 logs in as User A
        client1.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )

        # Verify Client 1 migrated, Client 2 untouched
        for s in sessions_client1:
            s.refresh_from_db()
            self.assertEqual(s.user, self.user_a)
            self.assertEqual(s.guest_session_key, "")

        for s in sessions_client2:
            s.refresh_from_db()
            self.assertIsNone(s.user)
            self.assertEqual(s.guest_session_key, key2)

        # Client 2 logs in as User B
        client2.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_b", "password": "StrongPassword456!"}),
            content_type="application/json",
        )

        for s in sessions_client2:
            s.refresh_from_db()
            self.assertEqual(s.user, self.user_b)
            self.assertEqual(s.guest_session_key, "")

        self.assertEqual(ChatSession.objects.filter(user=self.user_a).count(), 3)
        self.assertEqual(ChatSession.objects.filter(user=self.user_b).count(), 3)

    def test_11_migrated_session_access_and_security_in_chat_home_and_deletion(self):
        """
        Verify post-migration lifecycle:
        - Authenticated owner can access the migrated session in chat_home_view.
        - Unauthenticated guest or another user CANNOT load it as current_session.
        - Another user gets 403 trying to delete it.
        - Owner can delete it successfully.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        migrated_sess = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Security Lifecycle Session",
        )

        # Login as User A
        client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )

        # 1. Owner can access session
        owner_view = client.get(f"/?session={migrated_sess.id}")
        self.assertEqual(owner_view.status_code, 200)
        self.assertEqual(owner_view.context["current_session"], migrated_sess)

        # 2. Another user CANNOT access session as current_session
        client_b = Client()
        client_b.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_b", "password": "StrongPassword456!"}),
            content_type="application/json",
        )
        b_view = client_b.get(f"/?session={migrated_sess.id}")
        self.assertEqual(b_view.status_code, 200)
        self.assertIsNone(b_view.context["current_session"])

        # 3. Another user CANNOT delete it (403 Forbidden)
        del_attempt = client_b.post(reverse("chat:delete_session", args=[migrated_sess.id]))
        self.assertEqual(del_attempt.status_code, 403)
        self.assertTrue(ChatSession.objects.filter(id=migrated_sess.id).exists())

        # 4. Owner CAN delete it
        del_success = client.post(reverse("chat:delete_session", args=[migrated_sess.id]))
        self.assertEqual(del_success.status_code, 200)
        self.assertFalse(ChatSession.objects.filter(id=migrated_sess.id).exists())

    def test_12_stress_large_batch_session_migration(self):
        """
        Stress test: Guest accumulates 50 chat sessions.
        Migration must complete cleanly with all 50 sessions assigned to user.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        batch_sessions = [
            ChatSession(
                guest_session_key=guest_key,
                title=f"Batch Session #{i}",
                mode="META_COACH",
            )
            for i in range(50)
        ]
        ChatSession.objects.bulk_create(batch_sessions)
        self.assertEqual(ChatSession.objects.filter(guest_session_key=guest_key).count(), 50)

        # Log in
        res = client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        migrated_count = ChatSession.objects.filter(user=self.user_a).count()
        remaining_guest = ChatSession.objects.filter(guest_session_key=guest_key).count()

        self.assertEqual(migrated_count, 50)
        self.assertEqual(remaining_guest, 0)

    def test_13_session_rich_metadata_preservation(self):
        """
        Verify all rich metadata (mode, items, pinned, messages, generative UI cards, latency)
        is completely preserved without loss or corruption during migration.
        """
        client = Client()
        client.get(reverse("core:home"))
        guest_key = client.session.session_key

        sess = ChatSession.objects.create(
            guest_session_key=guest_key,
            title="Complex Hextech Opener Session",
            mode="OPENER_BUILDER",
            selected_items_json=["TFT_Item_BFSword", "TFT_Item_RecurveBow"],
            is_pinned=True,
        )

        msg1 = ChatMessage.objects.create(
            session=sess,
            role="user",
            content_markdown="B.F. ve Yay ile hangi açılışı yapmalıyım?",
        )
        msg2 = ChatMessage.objects.create(
            session=sess,
            role="assistant",
            content_markdown="Giant Slayer veya Guinsoo önceliklendirilebilir.",
            ui_cards_json=[
                {"card_type": "comp", "comp_name": "Rebel Snipers", "tier": "S"}
            ],
            cited_chunk_ids=["chunk_123"],
            latency_ms=180,
            model_used="gemini-2.5-flash",
        )

        # Log in
        client.post(
            reverse("accounts:login"),
            data=json.dumps({"username": "challenger_user_a", "password": "StrongPassword123!"}),
            content_type="application/json",
        )

        sess.refresh_from_db()
        self.assertEqual(sess.user, self.user_a)
        self.assertEqual(sess.guest_session_key, "")
        self.assertEqual(sess.mode, "OPENER_BUILDER")
        self.assertEqual(sess.selected_items_json, ["TFT_Item_BFSword", "TFT_Item_RecurveBow"])
        self.assertTrue(sess.is_pinned)

        msgs = list(sess.messages.order_by("id"))
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content_markdown, "B.F. ve Yay ile hangi açılışı yapmalıyım?")
        self.assertEqual(msgs[1].latency_ms, 180)
        self.assertEqual(msgs[1].model_used, "gemini-2.5-flash")
        self.assertEqual(msgs[1].ui_cards_json[0]["comp_name"], "Rebel Snipers")
