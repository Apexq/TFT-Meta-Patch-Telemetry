"""
Official Riot Games API Client for TFT Set 18 AI Coach.
Supports Regional routing (account-v1, tft-match-v1) and Platform routing (tft-league-v1)
with robust error handling, rate limit preservation, and PlayerMatchCache caching.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from apps.riot_sync.models import PlayerMatchCache

logger = logging.getLogger("apps.riot_sync")

# Mapping of platform shards to regional routing clusters
PLATFORM_TO_ROUTING: Dict[str, str] = {
    # Europe
    "tr1": "europe",
    "euw1": "europe",
    "eun1": "europe",
    "ru": "europe",
    # Americas
    "na1": "americas",
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    # Asia
    "kr": "asia",
    "jp1": "asia",
    # SEA
    "oc1": "sea",
    "ph2": "sea",
    "sg2": "sea",
    "th2": "sea",
    "tw2": "sea",
    "vn2": "sea",
}

ROUTING_TO_DEFAULT_PLATFORM: Dict[str, str] = {
    "europe": "tr1",
    "americas": "na1",
    "asia": "kr",
    "sea": "oc1",
}


class RiotApiError(Exception):
    """Base exception for Riot API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class RiotAuthError(RiotApiError):
    """Raised on 401/403: API key missing, invalid, or expired."""
    pass


class RiotNotFoundError(RiotApiError):
    """Raised on 404: Account, rank, or match not found."""
    pass


class RiotRateLimitError(RiotApiError):
    """Raised on 429: Riot API rate limit exceeded."""
    pass


class RiotApiClient:
    """
    Client for interacting with Riot Games official APIs:
    - account-v1 (Riot ID -> PUUID)
    - tft-league-v1 (Rank & LP)
    - tft-match-v1 (Match IDs & Match Details)
    """

    def __init__(self, api_key: Optional[str] = None, default_region: str = "TR1"):
        self.api_key = (
            api_key
            or os.getenv("RIOT_API_KEY")
            or getattr(settings, "RIOT_API_KEY", "")
        )
        self.default_region = default_region.upper()

    @staticmethod
    def get_routing_region(region: str) -> str:
        """Translates a platform shard (e.g. 'TR1') or regional name into routing region."""
        reg = region.lower().strip()
        if reg in PLATFORM_TO_ROUTING:
            return PLATFORM_TO_ROUTING[reg]
        if reg in ROUTING_TO_DEFAULT_PLATFORM:
            return reg
        return "europe"

    @staticmethod
    def get_platform_region(region: str) -> str:
        """Translates a routing cluster or platform into a valid platform shard."""
        reg = region.lower().strip()
        if reg in PLATFORM_TO_ROUTING:
            return reg
        if reg in ROUTING_TO_DEFAULT_PLATFORM:
            return ROUTING_TO_DEFAULT_PLATFORM[reg]
        return "tr1"

    def _request(self, url: str) -> Any:
        """
        Executes HTTP request to Riot API with X-Riot-Token header.
        Raises domain-specific exceptions for clean error propagation.
        """
        headers = {
            "User-Agent": "TFT-Set18-AICoach/1.0",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if self.api_key:
            headers["X-Riot-Token"] = self.api_key

        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
                if not content:
                    return None
                return json.loads(content.decode("utf-8"))
        except urllib.error.HTTPError as e:
            status = e.code
            logger.warning(f"Riot API HTTP {status} on {url}: {e.reason}")
            if status in (401, 403):
                raise RiotAuthError(
                    f"Riot API anahtarı geçersiz veya süresi dolmuş (HTTP {status}).",
                    status_code=status,
                )
            elif status == 404:
                raise RiotNotFoundError(
                    f"Riot API kaynağı bulunamadı (HTTP 404): {url}",
                    status_code=status,
                )
            elif status == 429:
                raise RiotRateLimitError(
                    "Riot API hız sınırı aşıldı (HTTP 429). Lütfen kısa bir süre sonra tekrar deneyin.",
                    status_code=status,
                )
            else:
                raise RiotApiError(
                    f"Riot API isteği başarısız oldu (HTTP {status}): {e.reason}",
                    status_code=status,
                )
        except urllib.error.URLError as e:
            logger.error(f"Riot API network error on {url}: {e.reason}")
            raise RiotApiError(f"Riot API sunucusuna ulaşılamadı: {e.reason}")
        except json.JSONDecodeError as e:
            logger.error(f"Riot API invalid JSON response: {e}")
            raise RiotApiError(f"Riot API geçersiz yanıt döndürdü: {e}")

    def resolve_riot_id(
        self, game_name: str, tag_line: str, region: str = "TR1"
    ) -> Dict[str, Any]:
        """
        Resolves Riot ID (gameName#tagLine) to PUUID via account-v1.
        Regional routing cluster is used.
        """
        routing = self.get_routing_region(region)
        encoded_name = urllib.parse.quote(game_name.strip())
        encoded_tag = urllib.parse.quote(tag_line.strip())
        url = (
            f"https://{routing}.api.riotgames.com"
            f"/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
        )
        data = self._request(url)
        if not data or not isinstance(data, dict):
            raise RiotNotFoundError(f"'{game_name}#{tag_line}' hesabı bulunamadı.")
        return {
            "puuid": data.get("puuid", ""),
            "gameName": data.get("gameName", game_name),
            "tagLine": data.get("tagLine", tag_line),
        }

    # Alias for method name compatibility
    get_account_by_riot_id = resolve_riot_id

    def get_tft_rank(self, puuid: str, region: str = "TR1") -> Dict[str, Any]:
        """
        Retrieves TFT ranked tier, division, and LP via tft-league-v1.
        Platform routing shard is used.
        """
        platform = self.get_platform_region(region)
        url = (
            f"https://{platform}.api.riotgames.com"
            f"/tft/league/v1/by-puuid/{puuid}"
        )
        try:
            data = self._request(url)
        except RiotNotFoundError:
            data = []
        except RiotApiError as exc:
            logger.warning(f"Non-fatal error fetching TFT rank for {puuid}: {exc}")
            data = []

        ranked_entry: Optional[Dict[str, Any]] = None
        if isinstance(data, list):
            for entry in data:
                if entry.get("queueType") == "RANKED_TFT":
                    ranked_entry = entry
                    break
            if not ranked_entry and data:
                ranked_entry = data[0]

        if ranked_entry:
            tier = ranked_entry.get("tier", "UNRANKED").upper()
            rank = ranked_entry.get("rank", "")
            lp = ranked_entry.get("leaguePoints", 0)
            wins = ranked_entry.get("wins", 0)
            losses = ranked_entry.get("losses", 0)

            # Master / Grandmaster / Challenger don't display Roman divisions
            if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
                badge = f"{tier} • {lp} LP"
            elif tier == "UNRANKED":
                badge = "UNRANKED"
            else:
                badge = f"{tier} {rank} • {lp} LP" if rank else f"{tier} • {lp} LP"

            return {
                "tier": tier,
                "rank": rank,
                "leaguePoints": lp,
                "badge": badge,
                "wins": wins,
                "losses": losses,
                "queueType": "RANKED_TFT",
            }

        return {
            "tier": "UNRANKED",
            "rank": "",
            "leaguePoints": 0,
            "badge": "UNRANKED",
            "wins": 0,
            "losses": 0,
            "queueType": "RANKED_TFT",
        }

    get_league_entries_by_puuid = get_tft_rank

    def get_recent_match_ids(
        self, puuid: str, region: str = "TR1", count: int = 5
    ) -> List[str]:
        """
        Retrieves recent TFT match IDs via tft-match-v1.
        Regional routing cluster is used.
        """
        routing = self.get_routing_region(region)
        count = max(1, min(count, 20))
        url = (
            f"https://{routing}.api.riotgames.com"
            f"/tft/match/v1/matches/by-puuid/{puuid}/ids?count={count}"
        )
        data = self._request(url)
        if isinstance(data, list):
            return [str(m) for m in data]
        return []

    get_match_ids_by_puuid = get_recent_match_ids

    def get_match_detail(self, match_id: str, region: str = "TR1") -> Dict[str, Any]:
        """
        Fetches full TFT match details from Riot API via tft-match-v1.
        Regional routing cluster is used.
        """
        routing = self.get_routing_region(region)
        url = f"https://{routing}.api.riotgames.com/tft/match/v1/matches/{match_id}"
        data = self._request(url)
        if not data or not isinstance(data, dict):
            raise RiotNotFoundError(f"Maç bulunamadı: {match_id}")
        return data

    get_match_details = get_match_detail

    def fetch_and_cache_player_matches(
        self,
        riot_id_or_name: str,
        tag_line: Optional[str] = None,
        region: str = "TR1",
        count: int = 5,
    ) -> Tuple[Dict[str, Any], List[PlayerMatchCache]]:
        """
        High-level pipeline:
        1. Resolves Riot ID -> PUUID.
        2. Retrieves TFT ranked badge.
        3. Fetches up to `count` recent match IDs.
        4. For each match, retrieves or checks PlayerMatchCache.
        5. If new match, runs MatchAnalyzer to compute lobby contested units,
           tempo, and BiS fit, then saves to PlayerMatchCache.
        Returns (player_info_dict, list_of_PlayerMatchCache_instances).
        """
        from apps.riot_sync.analyzer import MatchAnalyzer

        # Parse Riot ID
        if "#" in riot_id_or_name and tag_line is None:
            parts = riot_id_or_name.split("#", 1)
            game_name = parts[0].strip()
            tag_line = parts[1].strip()
        else:
            game_name = riot_id_or_name.strip()
            tag_line = (tag_line or region).strip()

        account = self.resolve_riot_id(game_name, tag_line, region)
        puuid = account["puuid"]
        full_riot_id = f"{account['gameName']}#{account['tagLine']}"

        # Fetch Rank
        rank_info = self.get_tft_rank(puuid, region)

        # Fetch Match IDs (larger window so skipped non-Set-18 games don't short-change the requested count)
        fetch_limit = min(20, max(count, count * 2)) if count <= 10 else count
        match_ids = self.get_recent_match_ids(puuid, region, count=fetch_limit)
        unit_catalog = MatchAnalyzer.get_set18_unit_catalog()

        cached_matches: List[PlayerMatchCache] = []

        for mid in match_ids:
            if len(cached_matches) >= count:
                break

            # Check per-player DB cache first
            cached_obj = PlayerMatchCache.objects.filter(match_id=mid, puuid=puuid).first()
            if cached_obj:
                cached_matches.append(cached_obj)
                continue

            # Fetch fresh match detail from Riot API
            try:
                detail = self.get_match_detail(mid, region)
            except Exception as e:
                logger.warning(f"Could not fetch match detail for {mid}: {e}")
                continue

            info = detail.get("info", {})
            metadata = detail.get("metadata", {})
            participants = info.get("participants", [])

            if not self._is_set18_match(info):
                logger.info(f"Skipping non-Set-18 match {mid} (set={info.get('tft_set_number')})")
                continue

            # Locate target player participant
            target_p = None
            for p in participants:
                if p.get("puuid") == puuid:
                    target_p = p
                    break

            if not target_p and participants:
                # Fallback to matching by riotId
                for p in participants:
                    if (
                        p.get("riotIdGameName", "").lower() == game_name.lower()
                        and p.get("riotIdTagline", "").lower() == tag_line.lower()
                    ):
                        target_p = p
                        break

            if not target_p:
                logger.warning(f"Target player {full_riot_id} ({puuid}) not found in match {mid}, skipping.")
                continue

            # Analyze match using MatchAnalyzer (Pillars 1, 2, 3)
            target_participant_puuid = target_p.get("puuid") or puuid
            analysis = MatchAnalyzer.analyze_match(detail, target_puuid=target_participant_puuid)

            # Extract board, traits, augments
            player_board = []
            for u in target_p.get("units", []):
                char_id = u.get("character_id", "")
                name = MatchAnalyzer.clean_name(char_id)
                cost = MatchAnalyzer.resolve_unit_cost(u, unit_catalog=unit_catalog, default=1)
                player_board.append({
                    "character_id": char_id,
                    "name": name,
                    "tier": u.get("tier", 1),
                    "cost": cost,
                    "items": u.get("itemNames", []),
                })

            active_traits = []
            for t in target_p.get("traits", []):
                if t.get("tier_current", 0) > 0 or t.get("num_units", 0) > 0:
                    t_name = t.get("name", "").replace("TFT18_", "")
                    active_traits.append({
                        "name": t_name,
                        "num_units": t.get("num_units", 0),
                        "tier_current": t.get("tier_current", 0),
                        "tier_total": t.get("tier_total", 3),
                        "style": t.get("style", 0),
                    })

            augments = target_p.get("augments", [])

            # Extract game datetime
            game_datetime_ms = info.get("game_datetime") or metadata.get("game_datetime", 0)
            if game_datetime_ms:
                game_dt = datetime.fromtimestamp(game_datetime_ms / 1000.0, tz=timezone.utc)
            else:
                game_dt = datetime.now(timezone.utc)

            # Format stage
            last_round_raw = target_p.get("last_round", "")
            last_round_stage = MatchAnalyzer.round_to_stage(last_round_raw)

            # Persist per-(match_id, puuid) cache cleanly
            match_cache, _ = PlayerMatchCache.objects.update_or_create(
                match_id=mid,
                puuid=puuid,
                defaults={
                    "riot_id_display": full_riot_id,
                    "region": region.upper(),
                    "patch_version": info.get("game_version", "Set 18 (18.6)"),
                    "placement": target_p.get("placement", 8),
                    "level": target_p.get("level", 8),
                    "gold_left": target_p.get("gold_left", 0),
                    "last_round": last_round_stage,
                    "player_board_json": player_board,
                    "active_traits_json": active_traits,
                    "augments_selected_json": augments,
                    "lobby_contested_json": analysis.get("lobby_contested_json", {}),
                    "ai_diagnosis_cache": analysis.get("diagnosis", {}),
                    "game_datetime": game_dt,
                },
            )
            cached_matches.append(match_cache)

        player_info = {
            "puuid": puuid,
            "riot_id": full_riot_id,
            "game_name": account["gameName"],
            "tag_line": account["tagLine"],
            "region": region.upper(),
            "rank": rank_info,
        }

        return player_info, cached_matches


    @classmethod
    def _is_set18_match(cls, info: Dict[str, Any]) -> bool:
        """
        Returns True when a match payload belongs to TFT Set 18 (or test fixtures without legacy prefixes).
        Filters out older Revival / legacy set matches (e.g., TFT15_).
        """
        tft_set = info.get("tft_set_number")
        if tft_set is not None:
            try:
                return int(tft_set) == 18
            except (ValueError, TypeError):
                pass

        participants = info.get("participants", [])
        legacy_prefixes = ("TFT15_", "TFT14_", "TFT13_", "TFT12_", "TFT16_", "TFT17_")
        saw_legacy = False
        saw_set18 = False
        for p in participants:
            for u in p.get("units", []):
                cid = str(u.get("character_id") or "")
                if cid.startswith("TFT18_") or cid.startswith("DA_18_") or cid.endswith("18") or cid.endswith("18_Base"):
                    saw_set18 = True
                elif cid.startswith(legacy_prefixes):
                    saw_legacy = True
        if saw_legacy and not saw_set18:
            return False
        return True


# Backward compatibility alias
RiotSyncClient = RiotApiClient
