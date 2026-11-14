"""
Signals for apps.accounts: auto-creating UserProfile and transferring guest chat sessions upon login.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.conf import settings

from apps.accounts.models import UserProfile
from apps.chat.models import ChatSession

User = get_user_model()


@receiver(post_save, sender=User)
def create_or_save_user_profile(sender, instance, created, **kwargs):
    """Ensures each User has an associated UserProfile."""
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def transfer_guest_sessions_on_login(sender, request, user, **kwargs):
    """
    Transfers pre-login guest ChatSession records to the newly logged-in user.
    Django's login() cycles the session key before firing user_logged_in,
    so views must attach request._guest_session_key before calling login().
    """
    guest_key = getattr(request, "_guest_session_key", None)
    if not guest_key and request:
        guest_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    if guest_key:
        ChatSession.objects.filter(guest_session_key=guest_key, user__isnull=True).update(
            user=user, guest_session_key=""
        )
