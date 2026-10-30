"""
Mathematical Diff Engine for TFT Set 18 (TFTSet18).
Compares Champions (base stats + 1/2/3-star ability scaling) and Traits
between two patches to classify BUFF, NERF, REWORK, or NEW changes and calculate Impact Scores.
Provides bilingual (TR / EN) labels for the dashboard language switcher.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.cdragon_client import CDragonClient

# Base stats: key -> (Turkish Label, English Label, Direction (+1 or -1), Weight)
STAT_RULES: Dict[str, Tuple[str, str, int, float]] = {
    "hp": ("Can (HP)", "Health (HP)", +1, 1.0),
    "damage": ("Saldırı Gücü (AD)", "Attack Damage (AD)", +1, 1.3),
    "attackSpeed": ("Saldırı Hızı (AS)", "Attack Speed (AS)", +1, 1.8),
    "armor": ("Zırh", "Armor", +1, 0.8),
    "magicResist": ("Büyü Direnci", "Magic Resist", +1, 0.8),
    "initialMana": ("Başlangıç Manası", "Starting Mana", +1, 0.6),
    "mana": ("Maksimum Mana", "Max Mana", -1, 1.6),
    "range": ("Menzil", "Attack Range", +1, 1.2),
}

IGNORED_VAR_KEYWORDS = ("tooltip", "hex", "index", "flag", "custom")


def _round_val(val: Any) -> float:
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return 0.0


def _format_num(val: float) -> str:
    if abs(val - round(val)) < 1e-3:
        return str(int(round(val)))
    return f"{val:.2f}".rstrip("0").rstrip(".")


def _format_star_values(values: List[float]) -> str:
    if not values:
        return "-"
    stars = values[1:4] if len(values) >= 4 else values[:3]
    if len(set(_round_val(x) for x in stars)) == 1:
        return _format_num(stars[0])
    return " / ".join(_format_num(x) for x in stars)


def _direction_for_ability_var(var_name: str) -> int:
    low = var_name.lower()
    if any(k in low for k in ("cooldown", "manalock", "cost", "delay")):
        return -1
    return +1


class Set18DiffEngine:
    """Computes structured patch diffs and impact scores for TFT Set 18."""

    def __init__(
        self,
        icon_version: str = "latest",
        en_champ_names: Optional[Dict[str, str]] = None,
        en_trait_names: Optional[Dict[str, str]] = None,
    ) -> None:
        self.icon_version = icon_version
        self.en_champ_names = en_champ_names or {}
        self.en_trait_names = en_trait_names or {}

    def compare_patches(
        self,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        old_label: str,
        new_label: str,
    ) -> Dict[str, Any]:
        champ_diffs = self._diff_champions(old_data.get("champions", []), new_data.get("champions", []))
        trait_diffs = self._diff_traits(old_data.get("traits", []), new_data.get("traits", []))

        buffed_champs = [c for c in champ_diffs if c["status"] == "BUFF"]
        nerfed_champs = [c for c in champ_diffs if c["status"] == "NERF"]
        reworked_champs = [c for c in champ_diffs if c["status"] in ("REWORK", "NEW")]

        buffed_traits = [t for t in trait_diffs if t["status"] == "BUFF"]
        nerfed_traits = [t for t in trait_diffs if t["status"] == "NERF"]

        return {
            "old_patch": old_label,
            "new_patch": new_label,
            "old_cdragon": old_data.get("cdragon_version"),
            "new_cdragon": new_data.get("cdragon_version"),
            "set_number": 18,
            "summary_counts": {
                "total_champions_changed": len(champ_diffs),
                "buffed_champions": len(buffed_champs),
                "nerfed_champions": len(nerfed_champs),
                "adjusted_champions": len(reworked_champs),
                "total_traits_changed": len(trait_diffs),
                "buffed_traits": len(buffed_traits),
                "nerfed_traits": len(nerfed_traits),
            },
            "champion_diffs": champ_diffs,
            "trait_diffs": trait_diffs,
        }

    def _diff_champions(
        self,
        old_champs: List[Dict[str, Any]],
        new_champs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        old_map = {c["apiName"]: c for c in old_champs}
        results: List[Dict[str, Any]] = []

        for nc in new_champs:
            api_name = nc["apiName"]
            oc = old_map.get(api_name)
            icon_url = CDragonClient.resolve_icon_url(
                nc.get("tileIcon") or nc.get("squareIcon") or nc.get("icon"),
                self.icon_version,
            )
            tr_name = nc.get("name", api_name)
            en_name = self.en_champ_names.get(api_name, tr_name)

            if not oc:
                results.append({
                    "apiName": api_name,
                    "name": tr_name,
                    "name_en": en_name,
                    "cost": nc.get("cost", 1),
                    "traits": nc.get("traits", []),
                    "icon": icon_url,
                    "status": "NEW",
                    "impact_score": 15.0,
                    "changes": [
                        {
                            "label": "Yeni Şampiyon",
                            "label_en": "New Champion",
                            "old": "-",
                            "new": "Added",
                            "delta_pct": 100.0,
                            "type": "BUFF",
                        }
                    ],
                })
                continue

            changes: List[Dict[str, Any]] = []
            total_score = 0.0

            # 1. Compare Base Stats
            old_stats = oc.get("stats", {})
            new_stats = nc.get("stats", {})
            for stat_key, (tr_label, en_label, direction, weight) in STAT_RULES.items():
                ov = _round_val(old_stats.get(stat_key, 0.0))
                nv = _round_val(new_stats.get(stat_key, 0.0))
                if abs(nv - ov) > 1e-3:
                    if ov == 0:
                        raw_pct = 15.0 if nv > 0 else -15.0
                    else:
                        raw_pct = ((nv - ov) / abs(ov)) * 100.0
                    effective_pct = raw_pct * direction
                    effective_pct = max(-35.0, min(35.0, effective_pct))
                    score_contrib = effective_pct * weight
                    total_score += score_contrib
                    changes.append({
                        "label": tr_label,
                        "label_en": en_label,
                        "old": _format_num(ov),
                        "new": _format_num(nv),
                        "delta_pct": round(effective_pct, 1),
                        "type": "BUFF" if effective_pct > 0 else "NERF",
                    })

            # 2. Compare Ability Scaling Variables (1* / 2* / 3*)
            old_vars = {
                v["name"]: v.get("value", [])
                for v in oc.get("ability", {}).get("variables", [])
                if v.get("name") and isinstance(v.get("value"), list)
            }
            new_vars = {
                v["name"]: v.get("value", [])
                for v in nc.get("ability", {}).get("variables", [])
                if v.get("name") and isinstance(v.get("value"), list)
            }

            for var_name, n_vals in new_vars.items():
                if any(ig in var_name.lower() for ig in IGNORED_VAR_KEYWORDS):
                    continue
                o_vals = old_vars.get(var_name)
                if not o_vals:
                    continue

                o_stars = [_round_val(x) for x in (o_vals[1:4] if len(o_vals) >= 4 else o_vals[:3])]
                n_stars = [_round_val(x) for x in (n_vals[1:4] if len(n_vals) >= 4 else n_vals[:3])]
                if not o_stars or not n_stars or len(o_stars) != len(n_stars):
                    continue

                if any(abs(ns - os) > 1e-3 for os, ns in zip(o_stars, n_stars)):
                    if sum(abs(x) for x in o_stars) < 1e-3 and sum(abs(x) for x in n_stars) < 1e-3:
                        continue
                    pct_deltas = []
                    for os_val, ns_val in zip(o_stars, n_stars):
                        if abs(os_val) > 1e-3:
                            pct_deltas.append(((ns_val - os_val) / abs(os_val)) * 100.0)
                    if not pct_deltas:
                        continue
                    avg_pct = sum(pct_deltas) / len(pct_deltas)
                    direction = _direction_for_ability_var(var_name)
                    effective_pct = max(-40.0, min(40.0, avg_pct * direction))
                    if abs(effective_pct) < 0.2:
                        continue
                    total_score += effective_pct * 1.1
                    changes.append({
                        "label": f"Yetenek ({var_name})",
                        "label_en": f"Ability ({var_name})",
                        "old": _format_star_values(o_vals),
                        "new": _format_star_values(n_vals),
                        "delta_pct": round(effective_pct, 1),
                        "type": "BUFF" if effective_pct > 0 else "NERF",
                    })

            if not changes:
                continue

            has_buff = any(c["type"] == "BUFF" for c in changes)
            has_nerf = any(c["type"] == "NERF" for c in changes)
            if total_score >= 1.5:
                status = "BUFF"
            elif total_score <= -1.5:
                status = "NERF"
            elif has_buff and has_nerf:
                status = "REWORK"
            else:
                status = "BUFF" if total_score >= 0 else "NERF"

            results.append({
                "apiName": api_name,
                "name": tr_name,
                "name_en": en_name,
                "cost": nc.get("cost", 1),
                "traits": nc.get("traits", []),
                "ability_name": nc.get("ability", {}).get("name", ""),
                "icon": icon_url,
                "status": status,
                "impact_score": round(total_score, 1),
                "changes": changes,
            })

        results.sort(key=lambda x: abs(x["impact_score"]), reverse=True)
        return results

    def _diff_traits(
        self,
        old_traits: List[Dict[str, Any]],
        new_traits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        old_map = {t["apiName"]: t for t in old_traits}
        results: List[Dict[str, Any]] = []

        for nt in new_traits:
            api_name = nt["apiName"]
            ot = old_map.get(api_name)
            if not ot:
                continue

            icon_url = CDragonClient.resolve_icon_url(nt.get("icon"), self.icon_version)
            old_effects = ot.get("effects", [])
            new_effects = nt.get("effects", [])

            changes: List[Dict[str, Any]] = []
            total_score = 0.0

            for idx, ne in enumerate(new_effects):
                if idx >= len(old_effects):
                    break
                oe = old_effects[idx]
                min_units = ne.get("minUnits", idx + 1)

                o_vars = oe.get("variables", {}) or {}
                n_vars = ne.get("variables", {}) or {}

                for v_key, nv_raw in n_vars.items():
                    if v_key not in o_vars:
                        continue
                    ov = _round_val(o_vars[v_key])
                    nv = _round_val(nv_raw)
                    if abs(nv - ov) > 1e-3 and abs(ov) > 1e-3:
                        pct = ((nv - ov) / abs(ov)) * 100.0
                        pct = max(-35.0, min(35.0, pct))
                        if abs(pct) < 0.2:
                            continue
                        total_score += pct * 0.9
                        changes.append({
                            "label": f"({min_units}) {v_key}",
                            "label_en": f"({min_units}) {v_key}",
                            "old": _format_num(ov),
                            "new": _format_num(nv),
                            "delta_pct": round(pct, 1),
                            "type": "BUFF" if pct > 0 else "NERF",
                        })

            if not changes:
                continue

            status = "BUFF" if total_score >= 0 else "NERF"
            tr_name = nt.get("name", api_name)
            en_name = self.en_trait_names.get(api_name, tr_name)
            results.append({
                "apiName": api_name,
                "name": tr_name,
                "name_en": en_name,
                "icon": icon_url,
                "status": status,
                "impact_score": round(total_score, 1),
                "changes": changes,
            })

        results.sort(key=lambda x: abs(x["impact_score"]), reverse=True)
        return results
