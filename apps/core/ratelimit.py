"""
Privacy-preserving IP/User rate limiter backed by RateLimitLog.
Stores only salted SHA-256 hashes (never raw client IP addresses).
"""

from __future__ import annotations

import hashlib
from typing import Tuple

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone

from apps.chat.models import RateLimitLog


def get_client_ip_hash(request: HttpRequest) -> str:
    """Returns a salted SHA-256 hash of the client IP address."""
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff and getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        client_ip = xff.split(",")[0].strip()
    else:
        client_ip = (request.META.get("REMOTE_ADDR") or "unknown").strip()
    raw = f"{settings.SECRET_KEY}:{client_ip}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def check_rate_limit(
    request: HttpRequest,
    scope: str,
    limit: int,
    period: str = "min",
    user_scoped: bool = False,
) -> Tuple[bool, int]:
    """
    Atomically increments and checks rate limit in RateLimitLog.
    period: 'min' (per minute) or 'day' (per UTC/local day).
    Returns (allowed, current_count).
    """
    if not getattr(settings, "RATELIMIT_ENABLED", True) or limit <= 0:
        return True, 0

    now = timezone.localtime()
    if period == "day":
        window_key = f"{scope}:day:{now.strftime('%Y%m%d')}"
    else:
        window_key = f"{scope}:min:{now.strftime('%Y%m%d%H%M')}"

    if user_scoped and getattr(request, "user", None) and request.user.is_authenticated:
        identifier = f"usr:{request.user.id}"
    else:
        identifier = f"ip:{get_client_ip_hash(request)}"

    try:
        with transaction.atomic():
            updated = RateLimitLog.objects.filter(
                identifier=identifier,
                window_key=window_key,
            ).update(request_count=F("request_count") + 1)
            if updated:
                count = (
                    RateLimitLog.objects.filter(identifier=identifier, window_key=window_key)
                    .values_list("request_count", flat=True)
                    .first()
                    or 1
                )
            else:
                try:
                    RateLimitLog.objects.create(
                        identifier=identifier,
                        window_key=window_key,
                        request_count=1,
                    )
                    count = 1
                except IntegrityError:
                    RateLimitLog.objects.filter(
                        identifier=identifier,
                        window_key=window_key,
                    ).update(request_count=F("request_count") + 1)
                    count = (
                        RateLimitLog.objects.filter(identifier=identifier, window_key=window_key)
                        .values_list("request_count", flat=True)
                        .first()
                        or 1
                    )
    except Exception:
        # Fail-open if SQLite is locked during transient concurrency, never crash healthy traffic
        return True, 0

    return count <= limit, count
