"""
Unit and integration tests for Riot Games API Client and Post-Game Match Analyzer (apps.riot_sync).
Uses unittest.mock to mock all external HTTP calls without live network dependencies.
"""

import json
import urllib.error
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.riot_sync.client import (
    RiotApiClient,
    RiotSyncClient,
    RiotApiError,
    RiotAuthError,
    RiotNotFoundError,
    RiotRateLimitError,
    PLATFORM_TO_ROUTING,
)
from apps.riot_sync.analyzer import MatchAnalyzer, POOL_SIZES
from apps.riot_sync.models import PlayerMatchCache


class FakeHttpResponse:
    """Mock for urllib.request.urlopen context manager."""
    def __init__(self, data, status: int = 200):
        self._data = data
        self.status = status

    def read(self) -> bytes:
        if isinstance(self._data, (dict, list)):
            return json.dumps(self._data).encode("utf-8")
        elif isinstance(self._data, str):
            return self._data.encode("utf-8")
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RiotApiClientTests(TestCase):
    """Tests for RiotApiClient routing, resolution, ranking, and error handling."""

    def setUp(self):
        self.client_obj = RiotApiClient(api_key="RGAPI-TEST-TOKEN", default_region="TR1")

    def test_routing_region_mapping(self):
        """Tests that platform shards correctly resolve to regional routing clusters."""
        self.assertEqual(RiotApiClient.get_routing_region("tr1"), "europe")
        self.assertEqual(RiotApiClient.get_routing_region("TR1"), "europe")
        self.assertEqual(RiotApiClient.get_routing_region("euw1"), "europe")
        self.assertEqual(RiotApiClient.get_routing_region("eun1"), "europe")
        self.assertEqual(RiotApiClient.get_routing_region("ru"), "europe")

        self.assertEqual(RiotApiClient.get_routing_region("na1"), "americas")
        self.assertEqual(RiotApiClient.get_routing_region("br1"), "americas")
        self.assertEqual(RiotApiClient.get_routing_region("la1"), "americas")

        self.assertEqual(RiotApiClient.get_routing_region("kr"), "asia")
        self.assertEqual(RiotApiClient.get_routing_region("jp1"), "asia")

        self.assertEqual(RiotApiClient.get_routing_region("oc1"), "sea")
        self.assertEqual(RiotApiClient.get_routing_region("sg2"), "sea")

    def test_platform_region_mapping(self):
        """Tests platform shard resolution."""
        self.assertEqual(RiotApiClient.get_platform_region("europe"), "tr1")
        self.assertEqual(RiotApiClient.get_platform_region("americas"), "na1")
        self.assertEqual(RiotApiClient.get_platform_region("tr1"), "tr1")
        self.assertEqual(RiotApiClient.get_platform_region("kr"), "kr")

    @patch("urllib.request.urlopen")
    def test_resolve_riot_id_success(self, mock_urlopen):
        """Tests resolve_riot_id URL construction and data parsing."""
        mock_urlopen.return_value = FakeHttpResponse({
            "puuid": "puuid-12345-67890",
            "gameName": "Apexq",
            "tagLine": "TR1",
        })

        res = self.client_obj.resolve_riot_id("Apexq", "TR1", region="TR1")

        self.assertEqual(res["puuid"], "puuid-12345-67890")
        self.assertEqual(res["gameName"], "Apexq")
        self.assertEqual(res["tagLine"], "TR1")

        # Verify request URL
        req = mock_urlopen.call_args[0][0]
        self.assertIn("europe.api.riotgames.com", req.full_url)
        self.assertIn("/riot/account/v1/accounts/by-riot-id/Apexq/TR1", req.full_url)
        self.assertEqual(req.headers.get("X-riot-token"), "RGAPI-TEST-TOKEN")

    @patch("urllib.request.urlopen")
    def test_resolve_riot_id_url_encoding(self, mock_urlopen):
        """Tests that game names with special characters are safely URL-encoded."""
        mock_urlopen.return_value = FakeHttpResponse({
            "puuid": "puuid-special",
            "gameName": "Çakıl Taş",
            "tagLine": "TR 1",
        })

        self.client_obj.resolve_riot_id("Çakıl Taş", "TR 1", region="TR1")
        req = mock_urlopen.call_args[0][0]
        self.assertNotIn("Çakıl Taş", req.full_url)
        self.assertIn("%C3%87ak%C4%B1l%20Ta%C5%9F", req.full_url)

    @patch("urllib.request.urlopen")
    def test_get_tft_rank_ranked_entry(self, mock_urlopen):
        """Tests get_tft_rank formatting for Diamond tier."""
        mock_urlopen.return_value = FakeHttpResponse([
            {
                "queueType": "RANKED_TFT",
                "tier": "DIAMOND",
                "rank": "II",
                "leaguePoints": 45,
                "wins": 34,
                "losses": 20,
            }
        ])

        rank = self.client_obj.get_tft_rank("puuid-12345", region="TR1")
        self.assertEqual(rank["tier"], "DIAMOND")
        self.assertEqual(rank["rank"], "II")
        self.assertEqual(rank["leaguePoints"], 45)
        self.assertEqual(rank["badge"], "DIAMOND II • 45 LP")

    @patch("urllib.request.urlopen")
    def test_get_tft_rank_master_tier(self, mock_urlopen):
        """Tests get_tft_rank badge formatting for Master tier (no roman numeral)."""
        mock_urlopen.return_value = FakeHttpResponse([
            {
                "queueType": "RANKED_TFT",
                "tier": "MASTER",
                "rank": "I",
                "leaguePoints": 245,
                "wins": 50,
                "losses": 30,
            }
        ])

        rank = self.client_obj.get_tft_rank("puuid-master", region="TR1")
        self.assertEqual(rank["badge"], "MASTER • 245 LP")

    @patch("urllib.request.urlopen")
    def test_get_tft_rank_unranked(self, mock_urlopen):
        """Tests get_tft_rank fallback when no ranked entry exists."""
        mock_urlopen.return_value = FakeHttpResponse([])

        rank = self.client_obj.get_tft_rank("puuid-unranked", region="TR1")
        self.assertEqual(rank["tier"], "UNRANKED")
        self.assertEqual(rank["badge"], "UNRANKED")

    @patch("urllib.request.urlopen")
    def test_get_recent_match_ids(self, mock_urlopen):
        """Tests get_recent_match_ids returns list of match strings."""
        mock_urlopen.return_value = FakeHttpResponse(["TR1_1001", "TR1_1002", "TR1_1003"])

        ids = self.client_obj.get_recent_match_ids("puuid-test", region="TR1", count=3)
        self.assertEqual(ids, ["TR1_1001", "TR1_1002", "TR1_1003"])

    @patch("urllib.request.urlopen")
    def test_auth_error_handling(self, mock_urlopen):
        """Tests that HTTP 401/403 raises RiotAuthError."""
        err = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
        mock_urlopen.side_effect = err

        with self.assertRaises(RiotAuthError):
            self.client_obj.resolve_riot_id("Test", "TR1")

    @patch("urllib.request.urlopen")
    def test_rate_limit_error_handling(self, mock_urlopen):
        """Tests that HTTP 429 raises RiotRateLimitError."""
        err = urllib.error.HTTPError("url", 429, "Rate Limit Exceeded", {}, None)
        mock_urlopen.side_effect = err

        with self.assertRaises(RiotRateLimitError):
            self.client_obj.resolve_riot_id("Test", "TR1")

    @patch("urllib.request.urlopen")
    def test_not_found_error_handling(self, mock_urlopen):
        """Tests that HTTP 404 raises RiotNotFoundError."""
        err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        mock_urlopen.side_effect = err

        with self.assertRaises(RiotNotFoundError):
            self.client_obj.resolve_riot_id("NonExistent", "0000")


class MatchAnalyzerTests(TestCase):
    """Tests for MatchAnalyzer: Contested Units, Economy & Tempo, BiS item fit, and Synthesis."""

    def test_round_to_stage_conversion(self):
        """Tests converting Riot integer round numbers to TFT stage strings."""
        self.assertEqual(MatchAnalyzer.round_to_stage(1), "1-1")
        self.assertEqual(MatchAnalyzer.round_to_stage(3), "1-3")
        self.assertEqual(MatchAnalyzer.round_to_stage(4), "2-1")
        self.assertEqual(MatchAnalyzer.round_to_stage(10), "2-7")
        self.assertEqual(MatchAnalyzer.round_to_stage(11), "3-1")
        self.assertEqual(MatchAnalyzer.round_to_stage(24), "4-7")
        self.assertEqual(MatchAnalyzer.round_to_stage(28), "5-4")
        self.assertEqual(MatchAnalyzer.round_to_stage(32), "6-1")
        self.assertEqual(MatchAnalyzer.round_to_stage("5-2"), "5-2")

    def test_analyze_contested_units_high_severity(self):
        """
        Tests detecting HIGH severity when 2 opponents contest the player's 4-cost LeBlanc
        (pool size 10, total copies >= 50% or >= 2 opponents).
        """
        player_units = [
            {"character_id": "TFT18_LeBlanc", "tier": 2, "cost": 4, "rarity": 4, "items": ["Item1", "Item2"]}
        ]
        # Opponents: 2 opponents holding LeBlanc (one 2-star = 3 copies, one 1-star = 1 copy)
        # Player has 3 copies -> Total = 7 copies out of 10 (70% pool depletion)
        opponents = [
            {"placement": 2, "units": [{"character_id": "TFT18_LeBlanc", "tier": 2, "cost": 4}]},
            {"placement": 6, "units": [{"character_id": "TFT18_LeBlanc", "tier": 1, "cost": 4}]},
            {"placement": 3, "units": [{"character_id": "TFT18_Sett", "tier": 2, "cost": 4}]},
            {"placement": 4, "units": []},
            {"placement": 5, "units": []},
            {"placement": 7, "units": []},
            {"placement": 8, "units": []},
        ]

        result = MatchAnalyzer.analyze_contested_units(player_units, opponents)

        self.assertTrue(result["is_heavily_contested"])
        self.assertEqual(len(result["contested_units"]), 1)
        cu = result["contested_units"][0]
        self.assertEqual(cu["unit_name"], "LeBlanc")
        self.assertEqual(cu["opponents_count"], 2)
        self.assertEqual(cu["pool_size"], 10)
        self.assertEqual(cu["lobby_copies_total"], 7)
        self.assertEqual(cu["pool_depleted_pct"], 70.0)
        self.assertEqual(cu["severity"], "HIGH")

    def test_analyze_contested_units_uncontested(self):
        """Tests that uncontested units return is_heavily_contested = False."""
        player_units = [
            {"character_id": "TFT18_Brambleback", "tier": 2, "cost": 4, "rarity": 4, "items": ["Item1", "Item2"]}
        ]
        opponents = [
            {"placement": 2, "units": [{"character_id": "TFT18_LeBlanc", "tier": 2}]},
            {"placement": 3, "units": [{"character_id": "TFT18_Sett", "tier": 2}]},
        ]

        result = MatchAnalyzer.analyze_contested_units(player_units, opponents)
        self.assertFalse(result["is_heavily_contested"])
        self.assertEqual(len(result["contested_units"]), 0)

    def test_analyze_economy_tempo_dead_gold(self):
        """Tests detection of Dead Gold syndrome when eliminated in bot 4 with >= 15 gold."""
        res = MatchAnalyzer.analyze_economy_and_tempo(
            placement=5,
            level=8,
            gold_left=22,
            last_round=28,
        )
        self.assertTrue(res["dead_gold"])
        self.assertIn("Dead Gold", res["critique_tr"])
        self.assertLess(res["economy_score"], 70)

    def test_analyze_economy_tempo_underleveled(self):
        """Tests detection of underleveling (Stage 5+ while still Level <= 7)."""
        res = MatchAnalyzer.analyze_economy_and_tempo(
            placement=6,
            level=7,
            gold_left=4,
            last_round="5-2",
        )
        self.assertTrue(res["underleveled"])
        self.assertIn("7. seviyede kalmışsınız", res["critique_tr"])

    def test_analyze_bis_fit_optimal(self):
        """Tests that LeBlanc with Spear of Shojin and Jeweled Gauntlet scores optimal."""
        units = [
            {
                "character_id": "TFT18_LeBlanc",
                "cost": 4,
                "tier": 2,
                "itemNames": ["TFT_Item_SpearOfShojin", "TFT_Item_JeweledGauntlet"],
            }
        ]
        res = MatchAnalyzer.analyze_bis_fit(units)
        self.assertEqual(len(res["carries"]), 1)
        carry = res["carries"][0]
        self.assertEqual(carry["rating"], "Optimal BiS")
        self.assertEqual(carry["fit_score"], 100)
        self.assertGreaterEqual(res["overall_bis_score"], 80)

    def test_analyze_bis_fit_anti_synergy(self):
        """Tests that LeBlanc with Deathblade (AD item on AP carry) is flagged as Anti-Synergy."""
        units = [
            {
                "character_id": "TFT18_LeBlanc",
                "cost": 4,
                "tier": 2,
                "itemNames": ["TFT_Item_Deathblade", "TFT_Item_RunaansHurricane"],
            }
        ]
        res = MatchAnalyzer.analyze_bis_fit(units)
        carry = res["carries"][0]
        self.assertEqual(carry["rating"], "Anti-Synergy")
        self.assertLessEqual(carry["fit_score"], 40)

    def test_analyze_match_synthesis(self):
        """Tests full synthesis into diagnosis payload and lobby_contested_json."""
        match_data = {
            "metadata": {"match_id": "TR1_999999"},
            "info": {
                "game_datetime": 1700000000000,
                "game_version": "Set 18 (18.6)",
                "participants": [
                    {
                        "puuid": "target-puuid",
                        "placement": 5,
                        "level": 8,
                        "gold_left": 18,
                        "last_round": 28,
                        "units": [
                            {"character_id": "TFT18_LeBlanc", "tier": 2, "cost": 4, "rarity": 4, "itemNames": ["Shojin", "JeweledGauntlet"]}
                        ],
                        "traits": [{"name": "TFT18_Coven", "num_units": 4, "tier_current": 2}],
                        "augments": ["Augment1"],
                    },
                    {
                        "puuid": "opp-1",
                        "placement": 2,
                        "level": 8,
                        "units": [{"character_id": "TFT18_LeBlanc", "tier": 2, "cost": 4, "rarity": 4}],
                    },
                    {
                        "puuid": "opp-2",
                        "placement": 3,
                        "level": 8,
                        "units": [{"character_id": "TFT18_LeBlanc", "tier": 1, "cost": 4, "rarity": 4}],
                    },
                ]
            }
        }

        result = MatchAnalyzer.analyze_match(match_data, target_puuid="target-puuid")

        self.assertIn("diagnosis", result)
        self.assertIn("lobby_contested_json", result)
        diag = result["diagnosis"]
        self.assertEqual(diag["placement"], 5)
        self.assertEqual(diag["primary_cause"], "CONTESTED_UNITS")
        self.assertTrue(len(diag["critical_mistakes"]) >= 1)
        self.assertTrue(len(diag["recommendations"]) >= 1)


class PlayerMatchCachingAndViewsTests(TestCase):
    """Tests for PlayerMatchCache DB persistence and HTTP view endpoints."""

    def setUp(self):
        self.client = Client()
        self.sample_match_id = "TR1_1234567890"
        self.puuid = "test-puuid-abc"
        self.riot_id = "Apexq#TR1"

    def test_fetch_and_cache_player_matches_persists_to_db(self):
        """Tests that fetching fresh matches creates PlayerMatchCache records in SQLite."""
        riot_client = RiotApiClient(api_key="TEST-TOKEN", default_region="TR1")

        mock_account = {"puuid": self.puuid, "gameName": "Apexq", "tagLine": "TR1"}
        mock_rank = {"tier": "PLATINUM", "rank": "I", "leaguePoints": 80, "badge": "PLATINUM I • 80 LP"}
        mock_match_detail = {
            "metadata": {"match_id": self.sample_match_id},
            "info": {
                "game_datetime": 1700000000000,
                "game_version": "Set 18 (18.6)",
                "participants": [
                    {
                        "puuid": self.puuid,
                        "placement": 4,
                        "level": 8,
                        "gold_left": 2,
                        "last_round": 32,
                        "units": [
                            {"character_id": "TFT18_Brambleback", "tier": 2, "cost": 4, "rarity": 4, "itemNames": ["Guinsoo"]}
                        ],
                        "traits": [{"name": "TFT18_Brawler", "num_units": 4, "tier_current": 2}],
                        "augments": ["Augment_A"],
                    }
                ]
            }
        }

        with patch.object(riot_client, "resolve_riot_id", return_value=mock_account), \
             patch.object(riot_client, "get_tft_rank", return_value=mock_rank), \
             patch.object(riot_client, "get_recent_match_ids", return_value=[self.sample_match_id]), \
             patch.object(riot_client, "get_match_detail", return_value=mock_match_detail):

            player_info, matches = riot_client.fetch_and_cache_player_matches("Apexq#TR1", region="TR1")

            self.assertEqual(len(matches), 1)
            cached_match = matches[0]
            self.assertEqual(cached_match.match_id, self.sample_match_id)
            self.assertEqual(cached_match.placement, 4)
            self.assertEqual(cached_match.riot_id_display, "Apexq#TR1")

            # Verify in Database
            db_record = PlayerMatchCache.objects.filter(match_id=self.sample_match_id).first()
            self.assertIsNotNone(db_record)
            self.assertEqual(db_record.level, 8)
            self.assertEqual(db_record.gold_left, 2)

            # Second call should read from DB without calling get_match_detail
            with patch.object(riot_client, "get_match_detail") as mock_fetch_detail:
                _, matches_2 = riot_client.fetch_and_cache_player_matches("Apexq#TR1", region="TR1")
                self.assertEqual(len(matches_2), 1)
                mock_fetch_detail.assert_not_called()

    def test_fetch_player_matches_view_get(self):
        """Tests GET /riot/player-matches/ endpoint returns match summaries."""
        # Pre-seed cache
        PlayerMatchCache.objects.create(
            match_id="TR1_TEST_VIEW",
            puuid=self.puuid,
            riot_id_display=self.riot_id,
            region="TR1",
            patch_version="Set 18",
            placement=3,
            level=8,
            gold_left=5,
            last_round="5-4",
            player_board_json=[{"name": "Sett", "tier": 2, "cost": 4}],
            active_traits_json=[{"name": "Brawler", "tier_current": 1}],
            augments_selected_json=["Aug1"],
            lobby_contested_json={"contested_units": [], "is_heavily_contested": False},
            ai_diagnosis_cache={"summary_headline": "#3 Sıralama Analizi"},
            game_datetime=timezone.now(),
        )

        with patch.object(RiotApiClient, "resolve_riot_id", return_value={"puuid": self.puuid, "gameName": "Apexq", "tagLine": "TR1"}), \
             patch.object(RiotApiClient, "get_tft_rank", return_value={"tier": "GOLD", "rank": "I", "leaguePoints": 50, "badge": "GOLD I • 50 LP"}), \
             patch.object(RiotApiClient, "get_recent_match_ids", return_value=["TR1_TEST_VIEW"]):

            resp = self.client.get(
                reverse("riot_sync:player_matches"),
                {"riot_id": "Apexq#TR1", "region": "TR1"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(len(data["matches"]), 1)
            self.assertEqual(data["matches"][0]["match_id"], "TR1_TEST_VIEW")
            self.assertEqual(data["matches"][0]["placement"], 3)

    def test_fetch_player_matches_view_missing_riot_id(self):
        """Tests that omitting riot_id returns 400 Bad Request."""
        resp = self.client.get(reverse("riot_sync:player_matches"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_analyze_match_view_cached(self):
        """Tests GET /riot/match/<match_id>/analyze/ endpoint with existing match cache."""
        PlayerMatchCache.objects.create(
            match_id="TR1_ANALYZE_1",
            puuid=self.puuid,
            riot_id_display=self.riot_id,
            region="TR1",
            patch_version="Set 18",
            placement=6,
            level=7,
            gold_left=25,
            last_round="5-1",
            player_board_json=[],
            active_traits_json=[],
            augments_selected_json=[],
            lobby_contested_json={"contested_units": [], "is_heavily_contested": False},
            ai_diagnosis_cache={"summary_headline": "#6 Sıralama: Dead Gold", "primary_cause": "DEAD_GOLD"},
            game_datetime=timezone.now(),
        )

        resp = self.client.get(
            reverse("riot_sync:analyze_match", kwargs={"match_id": "TR1_ANALYZE_1"})
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["match_id"], "TR1_ANALYZE_1")
        self.assertEqual(data["placement"], 6)
        self.assertIn("TR1_ANALYZE_1 numaralı maçımı analiz et", data["suggested_prompt"])

    def test_analyze_match_view_not_found(self):
        """Tests that requesting a non-existent match returns 404."""
        with patch.object(RiotApiClient, "get_match_detail", side_effect=RiotNotFoundError("Maç bulunamadı")):
            resp = self.client.get(
                reverse("riot_sync:analyze_match", kwargs={"match_id": "NON_EXISTENT_999"})
            )
            self.assertEqual(resp.status_code, 404)


class RiotChatPostGameIntegrationTests(TestCase):
    """
    Integration tests for end-to-end post-game match review wiring
    between apps.riot_sync and apps.chat (/chat/send/).
    """

    def setUp(self):
        self.client = Client()
        self.match = PlayerMatchCache.objects.create(
            match_id="TR1_DEMO_9988",
            puuid="puuid-integration-user",
            riot_id_display="CoachTester#TR1",
            region="TR1",
            patch_version="Set 18",
            placement=7,
            level=8,
            gold_left=22,
            last_round="5-2",
            player_board_json=[
                {"name": "LeBlanc", "tier": 2, "cost": 4, "items": ["Deathblade"]}
            ],
            active_traits_json=[{"name": "Sorcerer", "tier_current": 1}],
            augments_selected_json=["Aug1", "Aug2", "Aug3"],
            lobby_contested_json={
                "is_heavily_contested": True,
                "contested_units": [
                    {
                        "unit_name": "LeBlanc",
                        "player_tier": 2,
                        "severity": "HIGH",
                        "opponents_count": 2,
                        "pool_depleted_pct": 70.0,
                    }
                ],
            },
            ai_diagnosis_cache={
                "summary_headline": "#7 Sıralama Analizi: Dead Gold & Contested LeBlanc",
                "primary_cause": "DEAD_GOLD",
                "critical_mistakes": [
                    "Dead Gold: Elendiğinde 22 altının vardı.",
                    "Contested Birim: LeBlanc lobide 2 diğer oyuncu tarafından oynanıyordu.",
                ],
                "recommendations": [
                    "Canın kritik seviyedeyken roll down yap.",
                    "LeBlanc çok contested olduğunda AP alternatiflerine pivot et.",
                ],
            },
            game_datetime=timezone.now(),
        )

    def test_send_message_with_match_id_attaches_match_and_returns_review_card(self):
        """
        Posting to /chat/send/ with match_id sets session.attached_match,
        returns card_type: 'match_review' in message.ui_cards,
        and generates response content referencing the match analysis.
        """
        payload = {
            "query": "TR1_DEMO_9988 numaralı maçımı analiz et",
            "match_id": "TR1_DEMO_9988",
            "mode": "POST_GAME",
        }
        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # 1. ChatSession in DB has attached_match
        session_id = data["session_id"]
        from apps.chat.models import ChatSession
        session = ChatSession.objects.get(id=session_id)
        self.assertIsNotNone(session.attached_match)
        self.assertEqual(session.attached_match.match_id, "TR1_DEMO_9988")
        self.assertEqual(session.attached_match.placement, 7)
        self.assertEqual(session.mode, "POST_GAME")

        # 2. UI cards returns card_type: 'match_review' at index 0
        ui_cards = data["message"]["ui_cards"]
        self.assertTrue(len(ui_cards) > 0)
        match_card = ui_cards[0]
        self.assertEqual(match_card["card_type"], "match_review")
        self.assertEqual(match_card["match_id"], "TR1_DEMO_9988")
        self.assertEqual(match_card["placement"], 7)
        self.assertEqual(match_card["level"], 8)
        self.assertEqual(match_card["last_round"], "5-2")
        self.assertEqual(match_card["gold_left"], 22)
        self.assertTrue(match_card["is_heavily_contested"])
        self.assertEqual(len(match_card["contested_units"]), 1)
        self.assertEqual(match_card["contested_units"][0]["unit_name"], "LeBlanc")
        self.assertEqual(len(match_card["critical_mistakes"]), 2)
        self.assertEqual(len(match_card["recommendations"]), 2)

        # 3. Message content references match placement and diagnosis
        content = data["message"]["content"]
        self.assertIn("TR1_DEMO_9988", content)
        self.assertIn("LeBlanc", content)
        self.assertIn("22 altın", content)
        self.assertTrue("#7" in content or "7." in content or "7" in content, f"Expected placement in: {content}")

    def test_subsequent_messages_in_session_retain_awareness_of_attached_match(self):
        """
        Subsequent messages in the same session without match_id in the request body
        retain awareness of attached_match, preserving the link and returning match_review cards.
        """
        # Step 1: Initial inquiry with match_id
        init_res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({
                "query": "TR1_DEMO_9988 maçımı analiz et",
                "match_id": "TR1_DEMO_9988",
            }),
            content_type="application/json",
        )
        self.assertEqual(init_res.status_code, 200)
        session_id = init_res.json()["session_id"]

        # Step 2: Follow-up query in same session WITHOUT match_id
        followup_res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({
                "query": "Peki bir sonraki maçta ne yapmalıyım?",
                "session_id": session_id,
            }),
            content_type="application/json",
        )
        self.assertEqual(followup_res.status_code, 200)
        data2 = followup_res.json()

        # Check session still references attached_match
        from apps.chat.models import ChatSession
        session = ChatSession.objects.get(id=session_id)
        self.assertIsNotNone(session.attached_match)
        self.assertEqual(session.attached_match.match_id, "TR1_DEMO_9988")

        # Check match_review card is returned
        ui_cards = data2["message"]["ui_cards"]
        self.assertTrue(len(ui_cards) > 0)
        self.assertEqual(ui_cards[0]["card_type"], "match_review")
        self.assertEqual(ui_cards[0]["match_id"], "TR1_DEMO_9988")

        # Check content references the match telemetry context
        content2 = data2["message"]["content"]
        self.assertTrue(
            "LeBlanc" in content2
            or "22 altın" in content2
            or "TR1_DEMO_9988" in content2
            or "dead gold" in content2.lower()
            or "#7" in content2,
            f"Expected match context in follow-up response: {content2}"
        )

    def test_send_message_with_nonexistent_match_id(self):
        """Posting with an unknown match_id does not crash and handles gracefully."""
        res = self.client.post(
            reverse("chat:send_message"),
            data=json.dumps({
                "query": "Bilinmeyen maçımı analiz et",
                "match_id": "UNKNOWN_MATCH_123",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        ui_card_types = [c.get("card_type") for c in data["message"]["ui_cards"]]
        self.assertNotIn("match_review", ui_card_types)

