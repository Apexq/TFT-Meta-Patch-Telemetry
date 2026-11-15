"""
Views for apps.accounts: Registration, Login, Logout, Profile Management, and Status.
Supports both JSON responses (for AJAX/modals) and full-page HTML template rendering.
"""

from __future__ import annotations

import json
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.models import UserProfile
from apps.accounts.forms import (
    UserRegistrationForm,
    UserLoginForm,
    UserProfileUpdateForm,
)


def _is_json_request(request: HttpRequest) -> bool:
    """Helper to detect whether client expects JSON response."""
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in (request.content_type or "")
        or request.GET.get("format") == "json"
        or request.headers.get("accept", "").startswith("application/json")
    )


def _extract_request_data(request: HttpRequest) -> dict:
    """Extracts dict data from either JSON body or POST form data."""
    if "application/json" in (request.content_type or ""):
        try:
            return json.loads(request.body.decode("utf-8"))
        except Exception:
            return {}
    return request.POST.dict()


@require_http_methods(["GET", "POST"])
def register_view(request: HttpRequest) -> HttpResponse:
    """
    Handles user registration.
    On success: auto-logs in the user and transfers any guest chat sessions.
    """
    if request.user.is_authenticated:
        if _is_json_request(request):
            return JsonResponse({
                "status": "already_authenticated",
                "username": request.user.username,
                "redirect": "/",
            })
        return redirect("/")

    if request.method == "POST":
        data = _extract_request_data(request)
        form = UserRegistrationForm(data)

        if form.is_valid():
            user = form.save()

            # CRITICAL: Preserve guest session key before login() cycles it!
            session_key = request.session.session_key
            if not session_key:
                request.session.save()
                session_key = request.session.session_key
            request._guest_session_key = session_key

            login(request, user)

            if _is_json_request(request):
                return JsonResponse({
                    "status": "success",
                    "message": "Kayıt işlemi başarılı, oturum açıldı.",
                    "username": user.username,
                    "redirect": "/",
                })
            return redirect("/")
        else:
            if _is_json_request(request):
                return JsonResponse({
                    "status": "error",
                    "errors": form.errors,
                    "error": next(iter(form.errors.values()))[0] if form.errors else "Kayıt bilgileri geçersiz.",
                }, status=400)
            return render(request, "accounts/register.html", {"form": form})

    form = UserRegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    """
    Handles user login.
    On success: transfers any guest chat sessions to the authenticated user.
    """
    if request.user.is_authenticated:
        if _is_json_request(request):
            return JsonResponse({
                "status": "already_authenticated",
                "username": request.user.username,
                "redirect": "/",
            })
        return redirect("/")

    if request.method == "POST":
        data = _extract_request_data(request)
        form = UserLoginForm(data)

        if form.is_valid():
            user = getattr(form, "user", None)
            if not user:
                username = form.cleaned_data.get("username", "")
                password = form.cleaned_data.get("password", "")
                user = authenticate(request, username=username, password=password)

            if user is not None:
                # CRITICAL: Preserve guest session key before login() cycles it!
                session_key = request.session.session_key
                if not session_key:
                    request.session.save()
                    session_key = request.session.session_key
                request._guest_session_key = session_key

                login(request, user)

                raw_next = request.GET.get("next") or request.POST.get("next") or ""
                if raw_next and url_has_allowed_host_and_scheme(
                    url=raw_next,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    next_url = raw_next
                else:
                    next_url = "/"
                if _is_json_request(request):
                    return JsonResponse({
                        "status": "success",
                        "message": "Giriş başarılı.",
                        "username": user.username,
                        "redirect": next_url,
                    })
                return redirect(next_url)
            else:
                if _is_json_request(request):
                    return JsonResponse({
                        "status": "error",
                        "error": "Geçersiz kullanıcı adı veya şifre.",
                    }, status=400)
                form.add_error(None, "Geçersiz kullanıcı adı veya şifre.")
                return render(request, "accounts/login.html", {"form": form})
        else:
            if _is_json_request(request):
                return JsonResponse({
                    "status": "error",
                    "errors": form.errors,
                    "error": next(iter(form.errors.values()))[0] if form.errors else "Giriş bilgileri geçersiz.",
                }, status=400)
            return render(request, "accounts/login.html", {"form": form})

    form = UserLoginForm()
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    """
    Logs out the user and redirects to home.
    """
    logout(request)
    if _is_json_request(request):
        return JsonResponse({
            "status": "success",
            "message": "Çıkış yapıldı.",
            "redirect": "/",
        })
    return redirect("/")


@require_http_methods(["GET", "POST"])
def profile_view(request: HttpRequest) -> HttpResponse:
    """
    View and update user profile, Riot ID, preferred language, and view quota.
    """
    if not request.user.is_authenticated:
        if _is_json_request(request):
            return JsonResponse({"error": "Yetkisiz erişim. Lütfen giriş yapın."}, status=401)
        return redirect("accounts:login")

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.check_and_reset_quota()

    if request.method == "POST":
        data = _extract_request_data(request)
        form = UserProfileUpdateForm(data, instance=profile)

        if form.is_valid():
            form.save()
            quota_left = (
                profile.daily_quota_limit - profile.daily_quota_used
                if profile.plan_tier != "ADMIN"
                else 999999
            )
            if _is_json_request(request):
                return JsonResponse({
                    "status": "success",
                    "message": "Profil ve Riot ID ayarları güncellendi.",
                    "profile": {
                        "riot_game_name": profile.riot_game_name,
                        "riot_tag_line": profile.riot_tag_line,
                        "riot_region": profile.riot_region,
                        "preferred_lang": profile.preferred_lang,
                        "tier_badge": profile.tier_badge,
                        "plan_tier": profile.plan_tier,
                        "daily_quota_limit": profile.daily_quota_limit,
                        "daily_quota_used": profile.daily_quota_used,
                        "quota_left": quota_left,
                    }
                })
            return redirect("accounts:profile")
        else:
            if _is_json_request(request):
                return JsonResponse({
                    "status": "error",
                    "errors": form.errors,
                    "error": "Lütfen alanları kontrol ediniz.",
                }, status=400)
            return render(request, "accounts/profile.html", {"form": form, "profile": profile})

    # GET
    quota_left = (
        profile.daily_quota_limit - profile.daily_quota_used
        if profile.plan_tier != "ADMIN"
        else 999999
    )
    if _is_json_request(request):
        return JsonResponse({
            "username": request.user.username,
            "email": request.user.email,
            "riot_game_name": profile.riot_game_name,
            "riot_tag_line": profile.riot_tag_line,
            "riot_region": profile.riot_region,
            "preferred_lang": profile.preferred_lang,
            "tier_badge": profile.tier_badge,
            "plan_tier": profile.plan_tier,
            "daily_quota_limit": profile.daily_quota_limit,
            "daily_quota_used": profile.daily_quota_used,
            "quota_left": quota_left,
        })

    form = UserProfileUpdateForm(instance=profile)
    return render(request, "accounts/profile.html", {
        "form": form,
        "profile": profile,
        "quota_left": quota_left,
    })


def profile_status_view(request: HttpRequest) -> JsonResponse:
    """
    Returns JSON auth status, plan tier, and quota information for current session.
    """
    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.check_and_reset_quota()
        quota_left = (
            profile.daily_quota_limit - profile.daily_quota_used
            if profile.plan_tier != "ADMIN"
            else 999999
        )
        return JsonResponse({
            "authenticated": True,
            "auth": True,  # backwards-compatible
            "user": {
                "username": request.user.username,
                "email": request.user.email,
                "riot_game_name": profile.riot_game_name,
                "riot_tag_line": profile.riot_tag_line,
                "riot_region": profile.riot_region,
                "tier_badge": profile.tier_badge,
                "plan_tier": profile.plan_tier,
                "daily_quota_limit": profile.daily_quota_limit,
                "daily_quota_used": profile.daily_quota_used,
                "quota_left": quota_left,
                "preferred_lang": profile.preferred_lang,
            }
        })
    else:
        guest_used = request.session.get("guest_quota_used", 0)
        return JsonResponse({
            "authenticated": False,
            "auth": False,
            "user": None,
            "guest": {
                "daily_quota_limit": 30,
                "daily_quota_used": guest_used,
                "quota_left": max(0, 30 - guest_used),
                "plan_tier": "FREE",
            }
        })
