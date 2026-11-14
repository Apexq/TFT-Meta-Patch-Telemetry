"""
API views for apps.riot_sync.
Endpoints for resolving Riot IDs, retrieving ranked matches, and fetching AI post-game diagnosis.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET

from apps.riot_sync.client import (
    RiotApiClient,
    RiotApiError,
    RiotAuthError,
    RiotNotFoundError,
    RiotRateLimitError,
)
from apps.riot_sync.models import PlayerMatchCache
from apps.riot_sync.analyzer import MatchAnalyzer

logger = logging.getLogger("apps.riot_sync")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def fetch_player_matches_view(request: HttpRequest) -> JsonResponse:
    """
    Fetches a player's recent TFT matches by Riot ID (GameName#TagLine) and region.
    Resolves PUUID, fetches rank badge, caches matches in PlayerMatchCache,
    and returns match summaries with contested status and diagnosis.
    """
    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8"))
        except Exception:
            body = {}
        riot_id = body.get("riot_id") or body.get("summoner_name", "")
        region = body.get("region", "TR1")
        count = int(body.get("count", 5))
    else:
        riot_id = request.GET.get("riot_id") or request.GET.get("summoner_name", "")
        region = request.GET.get("region", "TR1")
        try:
            count = int(request.GET.get("count", 5))
        except (ValueError, TypeError):
            count = 5

    riot_id = (riot_id or "").strip()
    if not riot_id:
        return JsonResponse(
            {"error": "Riot ID zorunludur. Örnek: 'Oyuncu#TR1'"},
            status=400,
        )

    client = RiotApiClient(default_region=region)

    try:
        player_info, matches = client.fetch_and_cache_player_matches(
            riot_id_or_name=riot_id,
            region=region,
            count=count,
        )
    except RiotAuthError as e:
        return JsonResponse({"error": str(e), "error_type": "auth_error"}, status=403)
    except RiotNotFoundError as e:
        return JsonResponse({"error": str(e), "error_type": "not_found"}, status=404)
    except RiotRateLimitError as e:
        return JsonResponse({"error": str(e), "error_type": "rate_limit"}, status=429)
    except RiotApiError as e:
        return JsonResponse({"error": str(e), "error_type": "api_error"}, status=500)
    except Exception as e:
        logger.error(f"Unexpected error in fetch_player_matches_view: {e}", exc_info=True)
        return JsonResponse({"error": f"Beklenmeyen bir hata oluştu: {e}"}, status=500)

    matches_payload = []
    for m in matches:
        dt_str = m.game_datetime.isoformat() if hasattr(m.game_datetime, "isoformat") else str(m.game_datetime)
        matches_payload.append({
            "match_id": m.match_id,
            "placement": m.placement,
            "level": m.level,
            "gold_left": m.gold_left,
            "last_round": m.last_round,
            "game_datetime": dt_str,
            "player_board": m.player_board_json,
            "active_traits": m.active_traits_json,
            "augments": m.augments_selected_json,
            "contested_summary": (m.lobby_contested_json or {}).get("contested_units", []),
            "is_contested": (m.lobby_contested_json or {}).get("is_heavily_contested", False),
            "headline": (m.ai_diagnosis_cache or {}).get("summary_headline", f"#{m.placement} Sıralama"),
            "diagnosis": m.ai_diagnosis_cache,
        })

    return JsonResponse({
        "status": "success",
        "player": player_info,
        "matches": matches_payload,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def analyze_match_view(request: HttpRequest, match_id: str) -> JsonResponse:
    """
    Returns cached or computed full post-game diagnosis and coach prompt for a specific match.
    """
    match_id = match_id.strip()
    match_obj = PlayerMatchCache.objects.filter(match_id=match_id).first()

    if not match_obj:
        # Fallback: attempt to fetch match detail directly if possible
        region = request.GET.get("region", "TR1")
        client = RiotApiClient(default_region=region)
        try:
            detail = client.get_match_detail(match_id, region=region)
            target_puuid = request.GET.get("puuid") or ""
            analysis = MatchAnalyzer.analyze_match(detail, target_puuid=target_puuid)
            return JsonResponse({
                "status": "success",
                "match_id": match_id,
                "diagnosis": analysis.get("diagnosis", {}),
                "lobby_contested": analysis.get("lobby_contested_json", {}),
                "suggested_prompt": f"{match_id} numaralı maçımı analiz et. Hangi kritik hataları yaptım?",
            })
        except Exception as e:
            return JsonResponse(
                {"error": f"'{match_id}' kimlikli maç önbellekte bulunamadı ve Riot API'den alınamadı: {e}"},
                status=404,
            )

    dt_str = match_obj.game_datetime.isoformat() if hasattr(match_obj.game_datetime, "isoformat") else str(match_obj.game_datetime)
    suggested_prompt = (
        f"{match_obj.match_id} numaralı maçımı analiz et. "
        f"Neden #{match_obj.placement}. oldum ve hangi kritik hataları yaptım?"
    )

    return JsonResponse({
        "status": "success",
        "match_id": match_obj.match_id,
        "placement": match_obj.placement,
        "level": match_obj.level,
        "gold_left": match_obj.gold_left,
        "last_round": match_obj.last_round,
        "riot_id": match_obj.riot_id_display,
        "region": match_obj.region,
        "game_datetime": dt_str,
        "player_board": match_obj.player_board_json,
        "active_traits": match_obj.active_traits_json,
        "augments": match_obj.augments_selected_json,
        "lobby_contested": match_obj.lobby_contested_json,
        "diagnosis": match_obj.ai_diagnosis_cache,
        "suggested_prompt": suggested_prompt,
    })
