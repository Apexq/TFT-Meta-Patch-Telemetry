"""
Post-game match analyzer for TFT Set 18.
Evaluates:
- Pillar 1: Contested units across all 7 lobby opponents (bag pool depletion).
- Pillar 2: Economy, dead gold, and leveling tempo benchmarks.
- Pillar 3: Carry Best-in-Slot (BiS) item fit.
- Synthesis: Generates structured diagnosis payload for ai_diagnosis_cache & lobby_contested_json.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("apps.riot_sync")

# Riot tft-match-v1 sends 0-indexed rarity instead of gold cost for standard units
RARITY_TO_COST: Dict[int, int] = {
    0: 1,
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    6: 5,
    9: 5,
}

# Standard Set 18 Bag Pool Sizes
POOL_SIZES: Dict[int, int] = {
    1: 30,
    2: 25,
    3: 18,
    4: 10,
    5: 9,
}

# Unit copies by star tier
TIER_COPIES: Dict[int, int] = {
    1: 1,
    2: 3,
    3: 9,
    4: 27,
}

# Known Set 18 BiS / Synergistic Item Archetypes
KNOWN_BIS_CARRIES: Dict[str, Dict[str, Any]] = {
    "leblanc": {
        "role": "AP_CASTER",
        "bis": ["spear of shojin", "jeweled gauntlet", "nashor's tooth", "rabadon's deathcap", "archangel's staff", "shojin"],
        "good": ["guardbreaker", "giant slayer", "hand of justice", "blue buff", "morellonomicon", "void staff"],
        "bad": ["deathblade", "last whisper", "bloodthirster", "infinity edge", "runaan's hurricane"],
    },
    "brambleback": {
        "role": "AD_FIGHTER",
        "bis": ["edge of night", "guinsoo's rageblade", "quicksilver", "titan's resolve", "bloodthirster", "infinity edge"],
        "good": ["hand of justice", "sterak's gage", "giant slayer", "deathblade", "last whisper"],
        "bad": ["rabadon's deathcap", "jeweled gauntlet", "archangel's staff", "blue buff"],
    },
    "korkabuk": {
        "role": "AD_FIGHTER",
        "bis": ["edge of night", "guinsoo's rageblade", "quicksilver", "titan's resolve", "bloodthirster"],
        "good": ["hand of justice", "sterak's gage", "giant slayer", "deathblade", "last whisper"],
        "bad": ["rabadon's deathcap", "jeweled gauntlet", "archangel's staff", "blue buff"],
    },
    "sett": {
        "role": "AD_BRAWLER",
        "bis": ["bloodthirster", "titan's resolve", "sterak's gage", "hand of justice", "infinity edge"],
        "good": ["edge of night", "warmog's armor", "giant slayer", "deathblade"],
        "bad": ["rabadon's deathcap", "jeweled gauntlet", "blue buff", "archangel's staff"],
    },
    "elderdragon": {
        "role": "AD_LEGENDARY",
        "bis": ["infinity edge", "last whisper", "striker's flail", "deathblade", "giant slayer"],
        "good": ["bloodthirster", "edge of night", "hand of justice", "quicksilver"],
        "bad": ["rabadon's deathcap", "archangel's staff", "blue buff"],
    },
    "kadimejderha": {
        "role": "AD_LEGENDARY",
        "bis": ["infinity edge", "last whisper", "striker's flail", "deathblade", "giant slayer"],
        "good": ["bloodthirster", "edge of night", "hand of justice", "quicksilver"],
        "bad": ["rabadon's deathcap", "archangel's staff", "blue buff"],
    },
    "krug": {
        "role": "TANK",
        "bis": ["gargoyle stoneplate", "spirit visage", "warmog's armor", "dragon's claw", "bramble vest"],
        "good": ["protector's vow", "sunfire cape", "redemption", "steadfast heart", "ionic spark"],
        "bad": ["infinity edge", "deathblade", "rabadon's deathcap", "last whisper"],
    },
    "kayacil": {
        "role": "TANK",
        "bis": ["gargoyle stoneplate", "spirit visage", "warmog's armor", "dragon's claw", "bramble vest"],
        "good": ["protector's vow", "sunfire cape", "redemption", "steadfast heart", "ionic spark"],
        "bad": ["infinity edge", "deathblade", "rabadon's deathcap", "last whisper"],
    },
    "sentinel": {
        "role": "TANK",
        "bis": ["protector's vow", "warmog's armor", "gargoyle stoneplate", "dragon's claw", "bramble vest"],
        "good": ["redemption", "sunfire cape", "steadfast heart", "spirit visage", "ionic spark"],
        "bad": ["infinity edge", "deathblade", "rabadon's deathcap", "jeweled gauntlet"],
    },
    "gozcu": {
        "role": "TANK",
        "bis": ["protector's vow", "warmog's armor", "gargoyle stoneplate", "dragon's claw", "bramble vest"],
        "good": ["redemption", "sunfire cape", "steadfast heart", "spirit visage", "ionic spark"],
        "bad": ["infinity edge", "deathblade", "rabadon's deathcap", "jeweled gauntlet"],
    },
}


class MatchAnalyzer:
    """
    Core post-game analysis engine evaluating lobby contestation, economy/tempo,
    and BiS itemization for Set 18 matches.
    """

    @classmethod
    def round_to_stage(cls, round_val: Any) -> str:
        """
        Converts Riot round index (e.g. 28, 32) or string into standard TFT stage (e.g. '5-2').
        """
        if isinstance(round_val, str) and "-" in round_val:
            return round_val.strip()

        try:
            r = int(round_val)
        except (ValueError, TypeError):
            return "5-2"

        if r <= 0:
            return "1-1"
        elif r <= 3:
            return f"1-{r}"
        elif r <= 10:
            return f"2-{r - 3}"
        elif r <= 17:
            return f"3-{r - 10}"
        elif r <= 24:
            return f"4-{r - 17}"
        elif r <= 31:
            return f"5-{r - 24}"
        elif r <= 38:
            return f"6-{r - 31}"
        else:
            return f"7-{r - 38}"

    @classmethod
    def clean_name(cls, raw_name: str) -> str:
        """Strips TFT prefixes and technical Set/role suffixes for clean readable name."""
        if not raw_name:
            return ""
        s = str(raw_name).strip()
        for prefix in (
            "TFT18_",
            "TFT15_",
            "TFT14_",
            "TFT13_",
            "DA_18_",
            "DA_",
            "TFT_Item_",
            "TFT_",
            "Item_",
        ):
            s = s.replace(prefix, "")
        for suffix in ("_Base", "_base", "_AD", "_AP", "_Tank"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
        if s.endswith("18") and len(s) > 2:
            s = s[:-2]
        return s.strip()

    @staticmethod
    def _norm_key(raw: str) -> str:
        """Normalizes champion or item identifiers for fuzzy matching."""
        return "".join(ch for ch in str(raw or "").lower() if ch.isalnum())

    @classmethod
    def get_set18_unit_catalog(cls) -> Dict[str, Dict[str, Any]]:
        """
        Builds an index of Set 18 champions from the active PatchSnapshot
        (`tier_lists.unit_tiers`) mapping normalized IDs/names to exact gold cost and BiS items.
        """
        catalog: Dict[str, Dict[str, Any]] = {}
        try:
            from apps.telemetry.services import TelemetryRAGService
            snap = TelemetryRAGService.get_active_snapshot()
        except Exception:
            snap = None

        if not snap or not isinstance(snap.full_report_json, dict):
            return catalog

        unit_tiers = (
            snap.full_report_json.get("tier_lists", {}).get("unit_tiers", [])
            or []
        )
        for u in unit_tiers:
            if not isinstance(u, dict):
                continue
            cost_raw = u.get("cost")
            try:
                cost_val = int(cost_raw) if cost_raw is not None else 0
            except (ValueError, TypeError):
                cost_val = 0

            best_items = u.get("best_items") or []
            entry = {
                "apiName": u.get("apiName", ""),
                "name": u.get("name", ""),
                "name_en": u.get("name_en", ""),
                "cost": cost_val,
                "bis_en": [bi.get("name_en") or bi.get("name") or "" for bi in best_items if isinstance(bi, dict)],
                "bis_tr": [bi.get("name") or bi.get("name_en") or "" for bi in best_items if isinstance(bi, dict)],
                "bis_apis": [bi.get("apiName") or "" for bi in best_items if isinstance(bi, dict)],
            }

            keys = set()
            for candidate in (
                u.get("apiName", ""),
                cls.clean_name(u.get("apiName", "")),
                u.get("name_en", ""),
                u.get("name", ""),
            ):
                if candidate:
                    c_low = str(candidate).strip().lower()
                    keys.add(c_low)
                    keys.add(cls._norm_key(candidate))
                    if c_low.endswith("small") and len(c_low) > 5:
                        keys.add(c_low[:-5])
                        keys.add(cls._norm_key(c_low[:-5]))
            for k in keys:
                if k:
                    catalog.setdefault(k, entry)

        return catalog

    @classmethod
    def _lookup_catalog_entry(
        cls,
        char_id: str,
        unit_name: str = "",
        unit_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not unit_catalog:
            return None
        cleaned = cls.clean_name(char_id)
        for candidate in (char_id, cleaned, unit_name):
            if not candidate:
                continue
            low = str(candidate).strip().lower()
            if low in unit_catalog:
                return unit_catalog[low]
            normed = cls._norm_key(candidate)
            if normed in unit_catalog:
                return unit_catalog[normed]
        return None

    @classmethod
    def resolve_unit_cost(
        cls,
        unit: Dict[str, Any],
        unit_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
        default: int = 3,
    ) -> int:
        """
        Resolves true TFT gold cost (1-5) for a unit payload.
        Explicit 'cost' takes precedence; otherwise checks Set 18 CDragon/Snapshot catalog
        before mapping Riot's 0-indexed 'rarity' field.
        """
        explicit_cost = unit.get("cost")
        if explicit_cost is not None:
            try:
                c = int(explicit_cost)
                if 1 <= c <= 7:
                    return c
            except (ValueError, TypeError):
                pass

        char_id = unit.get("character_id") or unit.get("name") or ""
        entry = cls._lookup_catalog_entry(char_id, unit.get("name", ""), unit_catalog)
        if entry and 1 <= entry.get("cost", 0) <= 7:
            return int(entry["cost"])

        rarity = unit.get("rarity")
        if rarity is not None:
            try:
                r = int(rarity)
                if r in RARITY_TO_COST:
                    return RARITY_TO_COST[r]
                if 0 <= r <= 4:
                    return r + 1
            except (ValueError, TypeError):
                pass

        return default

    @classmethod
    def analyze_contested_units(
        cls,
        target_units: List[Dict[str, Any]],
        opponent_participants: List[Dict[str, Any]],
        unit_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Pillar 1: Compares player's units against all 7 lobby opponents.
        Calculates copy counts and bag pool depletion percentages.
        """
        if unit_catalog is None:
            unit_catalog = cls.get_set18_unit_catalog()

        contested_list = []
        is_heavily_contested = False

        for unit in target_units:
            char_id = unit.get("character_id") or unit.get("name") or ""
            clean_id = cls.clean_name(char_id).lower()
            player_tier = unit.get("tier", 1)
            player_copies = TIER_COPIES.get(player_tier, 1)
            cost = cls.resolve_unit_cost(unit, unit_catalog=unit_catalog, default=3)
            pool_size = POOL_SIZES.get(cost, 18)

            opponents_holding = 0
            opponents_copies = 0
            opponents_placements = []

            for opp in opponent_participants:
                opp_units = opp.get("units", [])
                opp_has_unit = False
                for ou in opp_units:
                    opp_char_id = ou.get("character_id") or ou.get("name") or ""
                    if cls.clean_name(opp_char_id).lower() == clean_id:
                        opp_has_unit = True
                        opp_tier = ou.get("tier", 1)
                        opp_copies = TIER_COPIES.get(opp_tier, 1)
                        opponents_copies += opp_copies

                if opp_has_unit:
                    opponents_holding += 1
                    if "placement" in opp:
                        opponents_placements.append(opp["placement"])

            total_lobby_copies = player_copies + opponents_copies
            pool_depleted_pct = round(min(100.0, (total_lobby_copies / pool_size) * 100), 1)

            # Determine severity
            if opponents_holding >= 2 or pool_depleted_pct >= 50.0:
                severity = "HIGH"
                is_heavily_contested = True
            elif opponents_holding >= 1 and (opponents_copies >= 3 or pool_depleted_pct >= 25.0):
                severity = "MEDIUM"
            elif opponents_holding >= 1:
                severity = "LOW"
            else:
                continue  # Not contested

            # Include if player cares: 3-star attempt, 4/5-cost carry, or 2+ items, or severity is HIGH/MEDIUM
            items_count = len(unit.get("itemNames") or unit.get("items") or [])
            if severity in ("HIGH", "MEDIUM") or items_count >= 2 or cost >= 4 or player_tier == 3:
                display_name = unit.get("name") or cls.clean_name(char_id)
                contested_list.append({
                    "unit_name": display_name,
                    "unit_id": char_id,
                    "cost": cost,
                    "player_tier": player_tier,
                    "player_copies": player_copies,
                    "opponents_count": opponents_holding,
                    "opponents_copies": opponents_copies,
                    "lobby_copies_total": total_lobby_copies,
                    "pool_size": pool_size,
                    "pool_depleted_pct": pool_depleted_pct,
                    "severity": severity,
                    "opponents_placements": sorted(opponents_placements),
                })

        # Generate readable summary
        if is_heavily_contested:
            high_units = [u["unit_name"] for u in contested_list if u["severity"] == "HIGH"]
            high_names = ", ".join(high_units) if high_units else "ana taşıyıcılarınız"
            summary_tr = f"Lobide {high_names} birimi için yüksek rekabet vardı (havuzun %50'sinden fazlası çekilmişti)."
            summary_en = f"Heavy competition in the lobby for {high_names} (over 50% of the bag pool was depleted)."
        elif contested_list:
            med_units = [u["unit_name"] for u in contested_list]
            summary_tr = f"Lobide {', '.join(med_units)} birimleri kısmen rakipler tarafından tutuluyordu."
            summary_en = f"Moderate competition for {', '.join(med_units)} across the lobby."
        else:
            summary_tr = "Lobide ana birimleriniz için belirgin bir rekabet yoktu (tahtanız uncontested idi)."
            summary_en = "Your primary units were mostly uncontested in the lobby."

        return {
            "contested_units": contested_list,
            "is_heavily_contested": is_heavily_contested,
            "summary_tr": summary_tr,
            "summary_en": summary_en,
        }

    @classmethod
    def analyze_economy_and_tempo(
        cls,
        placement: int,
        level: int,
        gold_left: int,
        last_round: Any,
    ) -> Dict[str, Any]:
        """
        Pillar 2: Economy & Leveling Tempo Benchmarks.
        Identifies "Dead Gold" syndrome, underleveling, and over-rolling.
        """
        stage_str = cls.round_to_stage(last_round)
        critiques_tr = []
        critiques_en = []

        is_dead_gold = False
        is_underleveled = False

        # Dead Gold Syndrome: Bot 4 exit with >= 15 gold unspent
        if placement >= 5 and gold_left >= 15:
            is_dead_gold = True
            critiques_tr.append(
                f"Elenirken elinizde {gold_left} altın vardı (Dead Gold)! "
                f"Canınız kritik seviyeye düştüğünde tahtayı yükseltmek için all-in yapmalıydınız."
            )
            critiques_en.append(
                f"Eliminated with {gold_left} unspent gold (Dead Gold)! "
                f"When health is in single digits, you must roll down all-in to stabilize."
            )

        # Underleveled Benchmark: Stage 5+ while remaining Level <= 7
        try:
            major_stage = int(stage_str.split("-")[0])
        except (ValueError, IndexError):
            major_stage = 5

        if major_stage >= 5 and level <= 7:
            is_underleveled = True
            critiques_tr.append(
                f"{stage_str} aşamasına ulaşmışken hâlâ 7. seviyede kalmışsınız. "
                f"4-altınlık ana taşıyıcıları sabitlemek için 4-2 veya 4-5'te 8. seviyeye çıkmalıydınız."
            )
            critiques_en.append(
                f"Reached stage {stage_str} while still at Level 7. "
                f"In Set 18, reaching Level 8 by 4-2 to 4-5 is essential for 4-cost carries."
            )

        # Economy rating score: 0 to 100
        score = 70
        if placement <= 4:
            score += 15
        if is_dead_gold:
            score -= 25
        if is_underleveled:
            score -= 20
        if placement >= 5 and gold_left <= 5:
            score += 10  # Tried their best rolling down
        if level >= 9:
            score += 10
        elif level >= 8:
            score += 5

        score = max(10, min(100, score))

        return {
            "last_round": stage_str,
            "level": level,
            "gold_left": gold_left,
            "dead_gold": is_dead_gold,
            "underleveled": is_underleveled,
            "economy_score": score,
            "critique_tr": " ".join(critiques_tr) if critiques_tr else "Ekonomi ve seviye basma temponuz stabil görünüyor.",
            "critique_en": " ".join(critiques_en) if critiques_en else "Your economy and leveling tempo were solid.",
        }

    @classmethod
    def analyze_bis_fit(
        cls,
        target_units: List[Dict[str, Any]],
        unit_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Pillar 3: Carry Best-in-Slot (BiS) Item Fit.
        Detects carry units and evaluates equipped items against optimal Set 18 itemization.
        """
        if unit_catalog is None:
            unit_catalog = cls.get_set18_unit_catalog()

        carries = []
        total_fit_scores = []

        # Find units with 2+ items or high-cost units with items
        for u in target_units:
            char_id = u.get("character_id") or u.get("name") or ""
            items = u.get("itemNames") or u.get("items") or []
            cost = cls.resolve_unit_cost(u, unit_catalog=unit_catalog, default=1)

            if len(items) >= 2 or (len(items) >= 1 and cost >= 4):
                clean_char = cls.clean_name(char_id).lower()
                unit_name = u.get("name") or cls.clean_name(char_id)

                # Look up carry profile: curated KNOWN_BIS_CARRIES first, then active PatchSnapshot catalog
                profile = KNOWN_BIS_CARRIES.get(clean_char)
                catalog_entry = cls._lookup_catalog_entry(char_id, unit_name, unit_catalog)
                dynamic_display_bis: List[str] = []

                if not profile and catalog_entry and (catalog_entry.get("bis_en") or catalog_entry.get("bis_apis")):
                    bis_candidates = [
                        cls.clean_name(x).lower()
                        for x in (catalog_entry.get("bis_en", []) + catalog_entry.get("bis_apis", []))
                        if x
                    ]
                    dynamic_display_bis = [x for x in (catalog_entry.get("bis_tr") or catalog_entry.get("bis_en") or []) if x]
                    profile = {
                        "role": "SNAPSHOT_META",
                        "bis": list(dict.fromkeys(bis_candidates)),
                        "good": [],
                        "bad": [],
                    }

                clean_items = [cls.clean_name(it).lower() for it in items]

                if profile:
                    bis_set = profile.get("bis", [])
                    good_set = profile.get("good", [])
                    bad_set = profile.get("bad", [])

                    bis_matches = 0
                    good_matches = 0
                    bad_matches = 0

                    for itm in clean_items:
                        norm_itm = cls._norm_key(cls.clean_name(itm))
                        if not norm_itm:
                            continue
                        if any(cls._norm_key(b) in norm_itm or norm_itm in cls._norm_key(b) for b in bis_set if cls._norm_key(b)):
                            bis_matches += 1
                        elif any(cls._norm_key(g) in norm_itm or norm_itm in cls._norm_key(g) for g in good_set if cls._norm_key(g)):
                            good_matches += 1
                        elif any(cls._norm_key(w) in norm_itm or norm_itm in cls._norm_key(w) for w in bad_set if cls._norm_key(w)):
                            bad_matches += 1

                    if bis_matches >= 3 or (len(items) == 2 and bis_matches == 2):
                        fit_score = 100
                        rating = "Optimal BiS"
                        critique_tr = f"{unit_name} üzerinde kurulan eşyalar tamamen optimal (BiS)."
                        critique_en = f"{unit_name} itemization is optimal BiS."
                    elif bis_matches >= 2 or (bis_matches == 1 and (good_matches >= 1 or profile.get("role") == "SNAPSHOT_META")):
                        fit_score = 80
                        rating = "Solid Flex"
                        critique_tr = f"{unit_name} üzerinde güçlü ve esnek eşya tercihi yapılmış."
                        critique_en = f"{unit_name} has strong, flexible itemization."
                    elif bad_matches > 0:
                        fit_score = 30
                        rating = "Anti-Synergy"
                        critique_tr = f"{unit_name} üzerinde uyumsuz / zayıf eşyalar bulunuyor."
                        critique_en = f"{unit_name} has anti-synergistic items."
                    else:
                        fit_score = 55
                        rating = "Suboptimal"
                        critique_tr = f"{unit_name} için daha ideal eşya kombinasyonları mümkündü."
                        critique_en = f"{unit_name} has suboptimal item combinations."

                    bis_display = dynamic_display_bis[:3] if dynamic_display_bis else [b.title() for b in bis_set[:3]]
                    carries.append({
                        "unit_name": unit_name,
                        "character_id": char_id,
                        "cost": cost,
                        "equipped_items": [cls.clean_name(it) for it in items],
                        "bis_items": bis_display,
                        "fit_score": fit_score,
                        "rating": rating,
                        "critique_tr": critique_tr,
                        "critique_en": critique_en,
                    })
                    total_fit_scores.append(fit_score)
                else:
                    # General heuristic if not in specific dictionary
                    fit_score = 75 if len(items) >= 3 else 60
                    carries.append({
                        "unit_name": unit_name,
                        "character_id": char_id,
                        "cost": cost,
                        "equipped_items": [cls.clean_name(it) for it in items],
                        "bis_items": ["Optimal Carry Eşyaları"],
                        "fit_score": fit_score,
                        "rating": "Solid",
                        "critique_tr": f"{unit_name} üzerinde {len(items)} tamamlanmış eşya bulunuyor.",
                        "critique_en": f"{unit_name} has {len(items)} completed items.",
                    })
                    total_fit_scores.append(fit_score)

        overall_score = round(sum(total_fit_scores) / len(total_fit_scores)) if total_fit_scores else 70

        return {
            "carries": carries,
            "overall_bis_score": overall_score,
        }

    @classmethod
    def analyze_match(
        cls,
        match_detail: Dict[str, Any],
        target_puuid: str,
    ) -> Dict[str, Any]:
        """
        Synthesizes Pillars 1, 2, and 3 into comprehensive ai_diagnosis_cache
        and lobby_contested_json structures.
        """
        info = match_detail.get("info", {})
        participants = info.get("participants", [])

        # Find target participant
        target_p = None
        other_participants = []
        for p in participants:
            if target_puuid and p.get("puuid") == target_puuid:
                target_p = p
            else:
                other_participants.append(p)

        if not target_p and participants:
            if not target_puuid:
                target_p = participants[0]
                other_participants = participants[1:]
            else:
                logger.warning("Target PUUID %s not found in match participants; skipping board attribution.", target_puuid)

        target_units = target_p.get("units", []) if target_p else []
        placement = target_p.get("placement", 8) if target_p else 8
        level = target_p.get("level", 8) if target_p else 8
        gold_left = target_p.get("gold_left", 0) if target_p else 0
        last_round = target_p.get("last_round", "") if target_p else ""

        # Run 3 Pillars (shared Set 18 unit catalog)
        unit_catalog = cls.get_set18_unit_catalog()
        contested_res = cls.analyze_contested_units(target_units, other_participants, unit_catalog=unit_catalog)
        economy_res = cls.analyze_economy_and_tempo(placement, level, gold_left, last_round)
        bis_res = cls.analyze_bis_fit(target_units, unit_catalog=unit_catalog)

        # Synthesize Primary Cause and Strengths / Mistakes
        strengths: List[str] = []
        mistakes: List[str] = []
        recommendations: List[str] = []

        primary_cause = "SOLID_GAME"

        if placement <= 4:
            strengths.append(f"Tebrikler! #{placement}. sırada bitirerek Top 4 LP kazandınız.")
            if bis_res["overall_bis_score"] >= 75:
                strengths.append("Taşıyıcı eşya dizilimleriniz metaya ve şampiyon kitlerine son derece uygundu.")
            if economy_res["economy_score"] >= 75:
                strengths.append(f"{economy_res['last_round']} aşamasına kadar tempolu seviye aldınız (Seviye {level}).")
            recommendations.append("Aynı seviye basma temposunu koruyarak 1.liğe oynamak için seviye 9'da 5-altınlık efsanevi birimler eklemeyi deneyin.")
        else:
            # Bot 4 Diagnosis
            if contested_res["is_heavily_contested"]:
                primary_cause = "CONTESTED_UNITS"
                high_c = [u["unit_name"] for u in contested_res["contested_units"] if u["severity"] == "HIGH"]
                names = ", ".join(high_c) if high_c else "ana birimleriniz"
                mistakes.append(f"Lobide 2 veya daha fazla rakip {names} oynuyordu ve havuz erkenden tükendi.")
                recommendations.append("Aşama 3-2 ve 4-1'de rakiplerin tahtalarını kontrol edin (scouting). Çok tutulan kompozisyonlarda inat etmek yerine boşta kalan alternatif taşıyıcılara pivot edin.")

            if economy_res["dead_gold"]:
                if primary_cause == "SOLID_GAME":
                    primary_cause = "DEAD_GOLD"
                mistakes.append(f"Elenirken elinizde {gold_left} altın kaldı (Dead Gold sendromu).")
                recommendations.append("Canınız 20'nin altına indiğinde faiz düşünmeden tüm paranızı harcayarak (all-in roll) tahtanızı sabitleyin.")

            if economy_res["underleveled"]:
                if primary_cause == "SOLID_GAME":
                    primary_cause = "UNDERLEVELED"
                mistakes.append(f"Geç aşamalara gelinmesine rağmen hâlâ 7. seviyede kalmışsınız.")
                recommendations.append("4-2 veya 4-5 civarında 8. seviyeye çıkarak 4-altınlık birimlerin çıkma oranını artırın.")

            if bis_res["overall_bis_score"] < 50:
                mistakes.append("Taşıyıcılarınız üzerinde uyumsuz veya zayıf eşyalar bulunuyordu.")
                recommendations.append("Erken aşamada esnek eşya bileşenleri seçin ve AD/AP rollerine uygun eşyalar birleştirin.")

            if not mistakes:
                mistakes.append(f"Lobi genel tempo olarak tahtanızı geride bıraktı (#{placement} sıra).")
                recommendations.append("Ön hat tank eşyalarını (Warmog, Gargoyle) erkenden birleştirerek can kaybını azaltın.")

        summary_headline = f"#{placement}. Sıra Analizi: {cls._format_cause_headline(primary_cause, placement)}"

        diagnosis_payload = {
            "summary_headline": summary_headline,
            "placement": placement,
            "level": level,
            "last_round": economy_res["last_round"],
            "gold_left": gold_left,
            "primary_cause": primary_cause,
            "strengths": strengths or ["Oyunun erken aşamasında tahtayı korumaya çalıştınız."],
            "critical_mistakes": mistakes,
            "recommendations": recommendations,
            "contested_summary": contested_res,
            "economy_summary": economy_res,
            "bis_summary": bis_res,
        }

        lobby_contested_payload = {
            "contested_units": contested_res["contested_units"],
            "is_heavily_contested": contested_res["is_heavily_contested"],
            "opponents_summary": [
                {
                    "puuid": opp.get("puuid"),
                    "placement": opp.get("placement"),
                    "level": opp.get("level"),
                    "units": [cls.clean_name(u.get("character_id", "")) for u in opp.get("units", [])[:6]],
                }
                for opp in other_participants
            ],
        }

        return {
            "contested": contested_res,
            "economy_tempo": economy_res,
            "bis_fit": bis_res,
            "diagnosis": diagnosis_payload,
            "lobby_contested_json": lobby_contested_payload,
        }

    @staticmethod
    def _format_cause_headline(cause: str, placement: int) -> str:
        if placement <= 4:
            return "Başarılı Top 4 Bitirişi"
        if cause == "CONTESTED_UNITS":
            return "Lobi Rekabeti ve Havuz Tükenmesi"
        elif cause == "DEAD_GOLD":
            return "Kullanılmayan Altın (Dead Gold) ile Elenme"
        elif cause == "UNDERLEVELED":
            return "Düşük Seviyede Kalma ve Geç Tempo"
        elif cause == "ITEMIZATION":
            return "Eşya Sinerji Eksikliği"
        return "Tempo ve Tahta Dayanıklılık Eksikliği"
