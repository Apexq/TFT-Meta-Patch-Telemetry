"""
Tests for Milestone 1: Single Chat Session Deletion (R1)
Verifies:
- Authenticated user can delete own session and cascade deletes ChatMessages.
- Guest user can delete own session and cascade deletes ChatMessages.
- Unauthorized attempts (other user, guest deleting auth session, cross-guest) return 403.
- Nonexistent session returns 404.
- Non-POST requests return 405 Method Not Allowed.
- Loading historical session via ?session=<uuid> works with proper authorization.
- STRICT CONSTRAINT: Absolutely NO "clear all history", "delete all", or bulk deletion buttons or endpoints exist.
- Frontend template contains trash button per session and Hextech confirmation modal.
"""

import uuid
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve, Resolver404

from apps.chat.models import ChatSession, ChatMessage

User = get_user_model()


@pytest.fixture
def auth_user():
    return User.objects.create_user(username="testplayer1", password="password123")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="testplayer2", password="password123")


@pytest.mark.django_db
def test_authenticated_user_can_delete_own_session(auth_user):
    """Authenticated user deletes their own session; verify cascading delete of messages."""
    client = Client()
    client.force_login(auth_user)

    session = ChatSession.objects.create(
        user=auth_user,
        title="Test Build LeBlanc",
        mode="META_COACH",
    )
    ChatMessage.objects.create(session=session, role="user", content_markdown="LeBlanc build nedir?")
    ChatMessage.objects.create(session=session, role="assistant", content_markdown="4 Meclis oynayabilirsiniz.")

    assert ChatMessage.objects.filter(session_id=session.id).count() == 2

    url = f"/chat/sessions/{session.id}/delete/"
    response = client.post(url)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["session_id"] == str(session.id)

    # Database verification
    assert not ChatSession.objects.filter(id=session.id).exists()
    assert ChatMessage.objects.filter(session_id=session.id).count() == 0


@pytest.mark.django_db
def test_guest_user_can_delete_own_session():
    """Guest user can delete their own session matching guest_session_key."""
    client = Client()
    # Establish a guest session
    client.get("/")
    session_key = client.session.session_key
    assert session_key

    guest_chat = ChatSession.objects.create(
        user=None,
        guest_session_key=session_key,
        title="Misafir Sohbeti",
        mode="META_COACH",
    )
    ChatMessage.objects.create(session=guest_chat, role="user", content_markdown="Guinsoo kimde iyi?")
    ChatMessage.objects.create(session=guest_chat, role="assistant", content_markdown="Kog'Maw veya Twitch.")

    assert ChatMessage.objects.filter(session_id=guest_chat.id).count() == 2

    url = f"/chat/sessions/{guest_chat.id}/delete/"
    response = client.post(url)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["session_id"] == str(guest_chat.id)

    assert not ChatSession.objects.filter(id=guest_chat.id).exists()
    assert ChatMessage.objects.filter(session_id=guest_chat.id).count() == 0


@pytest.mark.django_db
def test_authenticated_user_cannot_delete_other_user_session(auth_user, other_user):
    """Authenticated user cannot delete another user's session (returns 403)."""
    target_session = ChatSession.objects.create(
        user=other_user,
        title="Gizli Komp",
        mode="META_COACH",
    )
    ChatMessage.objects.create(session=target_session, role="user", content_markdown="Top secret comp")

    client = Client()
    client.force_login(auth_user)

    url = f"/chat/sessions/{target_session.id}/delete/"
    response = client.post(url)

    assert response.status_code == 403
    assert "Yetkisiz" in response.json().get("error", "")

    # Target session and messages must remain intact
    assert ChatSession.objects.filter(id=target_session.id).exists()
    assert ChatMessage.objects.filter(session_id=target_session.id).count() == 1


@pytest.mark.django_db
def test_guest_cannot_delete_authenticated_user_session(auth_user):
    """Unauthenticated guest cannot delete an authenticated user's session (returns 403)."""
    target_session = ChatSession.objects.create(
        user=auth_user,
        title="Auth User Session",
        mode="META_COACH",
    )

    client = Client()
    client.get("/")  # create guest session

    url = f"/chat/sessions/{target_session.id}/delete/"
    response = client.post(url)

    assert response.status_code == 403
    assert ChatSession.objects.filter(id=target_session.id).exists()


@pytest.mark.django_db
def test_guest_cannot_delete_another_guest_session():
    """A guest user cannot delete a different guest's session (returns 403)."""
    guest_session_b = ChatSession.objects.create(
        user=None,
        guest_session_key="different_guest_key_xyz",
        title="Guest B Session",
    )

    client = Client()
    client.get("/")  # gets a new session_key different from 'different_guest_key_xyz'

    url = f"/chat/sessions/{guest_session_b.id}/delete/"
    response = client.post(url)

    assert response.status_code == 403
    assert ChatSession.objects.filter(id=guest_session_b.id).exists()


@pytest.mark.django_db
def test_delete_nonexistent_session_returns_404():
    """Deleting a non-existent UUID returns 404."""
    client = Client()
    random_id = uuid.uuid4()
    url = f"/chat/sessions/{random_id}/delete/"
    response = client.post(url)

    assert response.status_code == 404
    assert "bulunamadı" in response.json().get("error", "")


@pytest.mark.django_db
def test_delete_session_requires_post(auth_user):
    """GET request to deletion endpoint returns 405 Method Not Allowed."""
    session = ChatSession.objects.create(user=auth_user, title="Test Session")
    client = Client()
    client.force_login(auth_user)

    url = f"/chat/sessions/{session.id}/delete/"
    response = client.get(url)

    assert response.status_code == 405
    assert ChatSession.objects.filter(id=session.id).exists()


@pytest.mark.django_db
def test_chat_home_loads_historical_session_if_authorized(auth_user, other_user):
    """chat_home_view properly loads historical session and messages for authorized user."""
    session = ChatSession.objects.create(user=auth_user, title="Auth Session 1")
    msg1 = ChatMessage.objects.create(session=session, role="user", content_markdown="Mesaj 1")
    msg2 = ChatMessage.objects.create(session=session, role="assistant", content_markdown="Cevap 1")

    client = Client()
    client.force_login(auth_user)

    resp = client.get(f"/?session={session.id}")
    assert resp.status_code == 200
    assert resp.context["current_session"] == session
    assert len(resp.context["chat_messages"]) == 2
    assert resp.context["chat_messages"][0] == msg1
    assert resp.context["chat_messages"][1] == msg2
    assert "Mesaj 1" in resp.content.decode("utf-8")

    # If another user tries to access this session in ?session=<id>, it should not load
    client.force_login(other_user)
    resp_other = client.get(f"/?session={session.id}")
    assert resp_other.status_code == 200
    assert resp_other.context["current_session"] is None
    assert len(resp_other.context["chat_messages"]) == 0


@pytest.mark.django_db
def test_no_clear_all_or_bulk_delete_buttons_or_endpoints():
    """
    STRICT CONSTRAINT TEST:
    Verify that NO 'clear all history', 'delete all', or bulk deletion buttons
    or endpoints exist in backend URLs or rendered templates.
    """
    client = Client()
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.content.decode("utf-8").lower()

    # Prohibited UI button / action texts (in TR and EN)
    prohibited_strings = [
        "tümünü temizle",
        "tüm geçmişi sil",
        "tüm sohbetleri sil",
        "clear all history",
        "delete all chats",
        "delete all sessions",
        "clear history",
        "delete-all",
        "clear-all",
        "delete_all",
        "clear_all",
    ]
    for term in prohibited_strings:
        assert term not in html, f"Prohibited bulk deletion text '{term}' found in chat_home.html"

    # Verify no bulk deletion URL paths resolve
    prohibited_endpoints = [
        "/chat/sessions/clear-all/",
        "/chat/sessions/delete-all/",
        "/chat/sessions/clear/",
        "/chat/clear-all/",
        "/chat/delete-all/",
        "/chat/sessions/bulk-delete/",
    ]
    for endpoint in prohibited_endpoints:
        with pytest.raises(Resolver404):
            resolve(endpoint)


@pytest.mark.django_db
def test_trash_icon_and_confirmation_modal_rendered_in_html(auth_user):
    """Verify trash icon per session item and Hextech confirmation modal in chat_home.html."""
    session = ChatSession.objects.create(user=auth_user, title="Silinecek Test Sohbeti")
    client = Client()
    client.force_login(auth_user)

    resp = client.get("/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Session item DOM container
    assert f'id="session-item-{session.id}"' in content
    # Trash button with onclick call to openDeleteSessionModal
    assert f"openDeleteSessionModal('{session.id}'" in content
    # Hextech confirmation modal elements
    assert 'id="delete-session-modal"' in content
    assert "Bu sohbeti silmek istediğinizden emin misiniz?" in content
    assert "confirm-delete-session-btn" in content
    assert "executeDeleteSession" in content


@pytest.mark.django_db
def test_chat_home_with_invalid_session_param_returns_200():
    """
    Verify that malformed, non-UUID, or injection ?session= query parameters
    gracefully return HTTP 200 without raising unhandled ValidationError or HTTP 500.
    """
    client = Client()
    malformed_session_params = [
        "not-a-uuid",
        "12345",
        "null",
        "undefined",
        "' OR 1=1 --",
        "123e4567-e89b-12d3-a456-42661417400Z",  # invalid hex char 'Z'
        "../../../etc/passwd",
        "",
    ]
    for param in malformed_session_params:
        resp = client.get(f"/?session={param}")
        assert resp.status_code == 200, f"Query ?session={param} returned {resp.status_code}, expected 200"
        assert resp.context["current_session"] is None
        assert resp.context["chat_messages"] == []


@pytest.mark.django_db
def test_chat_home_with_invalid_session_param_authenticated(auth_user):
    """
    Verify that an authenticated user supplying a malformed ?session= query parameter
    loads the homepage normally (200 OK) with current_session set to None.
    """
    client = Client()
    client.force_login(auth_user)

    resp = client.get("/?session=invalid-uuid-token")
    assert resp.status_code == 200
    assert resp.context["current_session"] is None
    assert resp.context["chat_messages"] == []

