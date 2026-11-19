"""
Main Orchestrator for TFT Set 18 Meta & Patch Intelligence Pipeline.
Supports:
- `--check-only`: Always queries live DDragon & CDragon (`force_refresh=True`) + checks Master+ telemetry freshness
- Full Pipeline Run: CDragon Set 18 Diff (Live & PBE, TR & EN) + Master+ Comps & Best-in-Slot Items + Official Riot API + Static Site Generation
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from src.cdragon_client import CDragonClient
from src.dashboard_builder import DashboardBuilder
from src.diff_engine import Set18DiffEngine
from src.meta_synthesizer import MetaSynthesizer
from src.rag_builder import RAGBuilder
from src.riot_client import RiotTFTAnalyzer

ROOT_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT_DIR / "data" / "state.json"


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _build_pbe_preview(
    pbe_data: Dict[str, Any],
    en_pbe_data: Dict[str, Any],
    pbe_en_champ_names: Dict[str, str],
    pbe_en_trait_names: Dict[str, str],
    versions: Dict[str, Any],
) -> Dict[str, Any]:
    """Builds a structured bilingual PBE catalog when PBE hosts a newer Set than Live."""
    en_traits_by_api = {t["apiName"]: t for t in (en_pbe_data or {}).get("traits", []) if t.get("apiName")}
    en_champs_by_api = {c["apiName"]: c for c in (en_pbe_data or {}).get("champions", []) if c.get("apiName")}
    en_trait_by_tr_name: Dict[str, str] = {}
    for t in pbe_data.get("traits", []):
        api = t.get("apiName")
        if api and t.get("name"):
            en_trait_by_tr_name[t["name"]] = pbe_en_trait_names.get(api, t["name"])

    champions_out = []
    for c in pbe_data.get("champions", []):
        api = c.get("apiName", "")
        cost = int(c.get("cost") or 1)
        tr_name = c.get("name") or api
        en_name = pbe_en_champ_names.get(api) or c.get("en_name") or tr_name
        en_c = en_champs_by_api.get(api, {})
        tr_traits = list(c.get("traits") or [])
        en_traits = list(en_c.get("traits") or [en_trait_by_tr_name.get(tr, tr) for tr in tr_traits])
        tr_ab = c.get("ability") or {}
        en_ab = en_c.get("ability") or {}
        champions_out.append({
            "apiName": api,
            "name": tr_name,
            "name_en": en_name,
            "cost": cost,
            "traits": tr_traits,
            "traits_en": en_traits,
            "ability_name": tr_ab.get("name", ""),
            "ability_name_en": en_ab.get("name", tr_ab.get("name", "")),
            "icon": CDragonClient.resolve_icon_url(c.get("tileIcon") or c.get("squareIcon") or c.get("icon"), "pbe"),
        })
    champions_out.sort(key=lambda x: (-x["cost"], x["name_en"]))

    traits_out = []
    for t in pbe_data.get("traits", []):
        api = t.get("apiName", "")
        tr_name = t.get("name") or api
        en_t = en_traits_by_api.get(api, {})
        en_name = pbe_en_trait_names.get(api, tr_name)
        breakpoints = [e.get("minUnits") for e in (t.get("effects") or []) if e.get("minUnits")]
        desc_tr = RiotTFTAnalyzer._clean_curve_tooltip(t.get("desc", ""), curve_values=t.get("curveValues"))
        desc_en = RiotTFTAnalyzer._clean_curve_tooltip(en_t.get("desc", ""), curve_values=en_t.get("curveValues")) or desc_tr
        traits_out.append({
            "apiName": api,
            "name": tr_name,
            "name_en": en_name,
            "desc": desc_tr,
            "desc_en": desc_en,
            "breakpoints": breakpoints,
            "icon": CDragonClient.resolve_icon_url(t.get("icon"), "pbe"),
        })
    traits_out.sort(key=lambda x: (-len(x["breakpoints"]), x["name_en"]))

    en_enc_by_api = {e.get("apiName"): e for e in (en_pbe_data or {}).get("encounters", []) if e.get("apiName")}
    encounters_out = []
    for enc in pbe_data.get("encounters", []):
        api = enc.get("apiName", "")
        en_e = en_enc_by_api.get(api, {})
        tr_name = enc.get("name") or api
        en_name = enc.get("en_name") or en_e.get("name") or tr_name
        desc_tr = RiotTFTAnalyzer._clean_curve_tooltip(enc.get("postSpawnDesc") or enc.get("desc") or "")
        desc_en = RiotTFTAnalyzer._clean_curve_tooltip(en_e.get("postSpawnDesc") or en_e.get("desc") or "") or desc_tr
        encounters_out.append({
            "apiName": api,
            "name": tr_name,
            "name_en": en_name,
            "desc": desc_tr,
            "desc_en": desc_en,
        })

    return {
        "is_new_set": True,
        "set_number": int(pbe_data.get("set_number") or 19),
        "mutator": pbe_data.get("mutator", "TFTSet19"),
        "patch_label": versions.get("pbe_label", "19.1 (PBE)"),
        "source": pbe_data.get("pbe_source", "CommunityDragon PBE"),
        "total_champions": len(champions_out),
        "total_traits": len(traits_out),
        "five_cost_count": sum(1 for c in champions_out if c["cost"] == 5),
        "champions": champions_out,
        "traits": traits_out,
        "encounters": encounters_out,
    }


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def write_github_output(outputs: Dict[str, str]) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a", encoding="utf-8") as f:
        for k, v in outputs.items():
            f.write(f"{k}={v}\n")


def _is_meta_telemetry_stale(prev_state: Dict[str, Any], max_hours: float = 12.0) -> bool:
    """Returns True if the last Master+ meta update is older than `max_hours`."""
    updated_str = prev_state.get("updated_at", "")
    if not updated_str:
        return True
    try:
        last_dt = datetime.strptime(updated_str, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        elapsed_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
        return elapsed_hours >= max_hours
    except Exception:
        return True


def run_pipeline(check_only: bool = False, force: bool = False) -> Dict[str, Any]:
    tr_client = CDragonClient(lang="tr_tr")
    versions = tr_client.resolve_patch_lifecycle_versions()

    print(
        f"[TFT Set 18] Patch Lifecycle: {versions['previous_label']} ({versions['previous_cdragon']}) "
        f"-> {versions['latest_label']} ({versions['latest_cdragon']}) "
        f"| PBE: {versions['pbe_label']} | DDragon: {versions.get('ddragon_version', '-')}"
    )

    try:
        latest_data = tr_client.fetch_set18_data(versions["latest_cdragon"], force_refresh=check_only)
        pbe_data = tr_client.fetch_set18_data("pbe", force_refresh=check_only)
    except RuntimeError as exc:
        if check_only and not force:
            print(f"[Check-Only Warning] CommunityDragon unreachable ({exc}); skipping run cleanly.")
            write_github_output({"should_run": "false", "live_changed": "false", "pbe_changed": "false", "meta_stale": "false"})
            return {"should_run": False, "versions": versions}
        raise

    live_set_num = int(latest_data.get("set_number", 18))
    pbe_set_num = int(pbe_data.get("set_number", live_set_num))
    if pbe_set_num != live_set_num:
        versions["pbe_set_number"] = pbe_set_num
        versions["pbe_mutator"] = pbe_data.get("mutator", f"TFTSet{pbe_set_num}")
        versions["pbe_label"] = pbe_data.get("patch_label") or f"{pbe_set_num}.1 (PBE)"
        print(f"[PBE Set Transition] Detected Set {pbe_set_num} on PBE: {versions['pbe_label']} (source: {pbe_data.get('pbe_source')})")
    else:
        versions["pbe_set_number"] = live_set_num
        versions["pbe_mutator"] = pbe_data.get("mutator", "TFTSet18")

    latest_fp = CDragonClient.compute_set18_fingerprint(latest_data)
    pbe_fp = CDragonClient.compute_set18_fingerprint(pbe_data)

    prev_state = load_state()
    live_changed = (
        prev_state.get("latest_cdragon") != versions["latest_cdragon"]
        or prev_state.get("ddragon_version") != versions.get("ddragon_version")
        or prev_state.get("latest_fingerprint") != latest_fp
    )
    pbe_changed = (
        prev_state.get("pbe_fingerprint") != pbe_fp
        or prev_state.get("pbe_set_number") != pbe_set_num
    )
    meta_stale = _is_meta_telemetry_stale(prev_state, max_hours=12.0)

    should_run = (
        force
        or live_changed
        or pbe_changed
        or meta_stale
        or not (ROOT_DIR / "docs" / "index.html").exists()
    )

    write_github_output({
        "should_run": "true" if should_run else "false",
        "live_changed": "true" if live_changed else "false",
        "pbe_changed": "true" if pbe_changed else "false",
        "meta_stale": "true" if meta_stale else "false",
        "latest_label": versions["latest_label"],
        "previous_label": versions["previous_label"],
        "pbe_label": versions["pbe_label"],
    })

    if check_only:
        print(
            f"[Check-Only] should_run={should_run} "
            f"(live_changed={live_changed}, pbe_changed={pbe_changed}, meta_stale={meta_stale}, pbe_set={pbe_set_num})"
        )
        return {"should_run": should_run, "versions": versions}

    prev_data = tr_client.fetch_set18_data(versions["previous_cdragon"])

    en_client = CDragonClient(lang="en_us")
    en_latest = en_client.fetch_set18_data(versions["latest_cdragon"])
    en_champ_names = {c["apiName"]: c.get("name", c["apiName"]) for c in en_latest.get("champions", [])}
    en_trait_names = {t["apiName"]: t.get("name", t["apiName"]) for t in en_latest.get("traits", [])}

    pbe_en_champ_names = dict(en_champ_names)
    pbe_en_trait_names = dict(en_trait_names)
    en_pbe_data: Dict[str, Any] = {}
    if pbe_set_num != live_set_num:
        try:
            en_pbe_data = en_client.fetch_set18_data("pbe", force_refresh=force)
            for c in en_pbe_data.get("champions", []):
                pbe_en_champ_names[c["apiName"]] = c.get("en_name") or c.get("name", c["apiName"])
            for t in en_pbe_data.get("traits", []):
                pbe_en_trait_names[t["apiName"]] = t.get("name", t["apiName"])
        except Exception as exc:
            print(f"[Warning] Failed to fetch English PBE metadata: {exc}")

    tr_items = latest_data.get("items", {})
    en_items = en_latest.get("items", {})

    diff_engine = Set18DiffEngine(
        icon_version=versions["latest_cdragon"],
        en_champ_names=en_champ_names,
        en_trait_names=en_trait_names,
    )
    live_diff = diff_engine.compare_patches(
        prev_data,
        latest_data,
        versions["previous_label"],
        versions["latest_label"],
    )

    pbe_diff_engine = Set18DiffEngine(
        icon_version="pbe",
        en_champ_names=pbe_en_champ_names,
        en_trait_names=pbe_en_trait_names,
    )
    pbe_diff = pbe_diff_engine.compare_patches(
        latest_data,
        pbe_data,
        versions["latest_label"],
        versions["pbe_label"],
    )

    riot_analyzer = RiotTFTAnalyzer(
        en_champ_names=en_champ_names,
        en_trait_names=en_trait_names,
        tr_items=tr_items,
        en_items=en_items,
    )
    riot_telemetry = riot_analyzer.fetch_official_riot_api_telemetry()
    print(f"[Riot Official API] Connected={riot_telemetry.get('connected')} | {riot_telemetry.get('status_tr')}")

    leaderboards = riot_analyzer.fetch_regional_leaderboards(limit_per_region=25)
    print(f"[Leaderboards] Fetched {leaderboards.get('total_players_listed', 0)} Challenger players across {len(leaderboards.get('regions', []))} regions")

    tier_lists = riot_analyzer.fetch_item_and_unit_tier_lists(
        set18_data=latest_data,
        diff_report=live_diff,
        icon_version=versions["latest_cdragon"],
    )
    print(f"[Tier Lists] Items={len(tier_lists.get('item_tiers', []))} | Units={len(tier_lists.get('unit_tiers', []))}")

    live_meta = riot_analyzer.build_set18_meta_compositions(
        set18_data=latest_data,
        diff_report=live_diff,
        is_pbe=False,
        icon_version=versions["latest_cdragon"],
        riot_telemetry=riot_telemetry,
    )
    pbe_meta = riot_analyzer.build_set18_meta_compositions(
        set18_data=pbe_data,
        diff_report=pbe_diff,
        is_pbe=True,
        icon_version="pbe",
        riot_telemetry=riot_telemetry,
    )

    augments_data = riot_analyzer.fetch_augment_tier_list(
        set18_data=latest_data,
        icon_version=versions["latest_cdragon"],
        meta_compositions=live_meta.get("compositions", []),
    )
    print(f"[Augments] Extracted {augments_data.get('total_augments', 0)} Set 18 augments (S:{augments_data.get('tier_counts', {}).get('S', 0)}, A:{augments_data.get('tier_counts', {}).get('A', 0)})")

    mechanics_data = riot_analyzer.fetch_set18_mechanics_telemetry(
        set18_data=latest_data,
        icon_version=versions["latest_cdragon"],
        meta_compositions=live_meta.get("compositions", []),
    )
    print(f"[Set 18 Mechanics] Encounters={mechanics_data.get('total_encounters', 0)} | Curated Charms={len(mechanics_data.get('charms', []))}")

    synthesizer = MetaSynthesizer()
    ai_summary = synthesizer.generate_turkish_meta_summary(
        live_diff=live_diff,
        live_meta=live_meta,
        pbe_diff=pbe_diff,
        pbe_meta=pbe_meta,
    )

    pbe_preview = (
        _build_pbe_preview(pbe_data, en_pbe_data, pbe_en_champ_names, pbe_en_trait_names, versions)
        if pbe_set_num != live_set_num
        else None
    )

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    full_report = {
        "generated_at": now_str,
        "set_number": 18,
        "mutator": "TFTSet18",
        "versions": versions,
        "ai_summary": ai_summary,
        "live_diff": live_diff,
        "live_meta": live_meta,
        "pbe_diff": pbe_diff,
        "pbe_meta": pbe_meta,
        "pbe_preview": pbe_preview,
        "leaderboards": leaderboards,
        "tier_lists": tier_lists,
        "augments": augments_data,
        "mechanics": mechanics_data,
        "chat": {
            # Public URL of the Cloudflare Worker AI Coach (not a secret). Empty = widget shows "coming soon".
            "endpoint": os.environ.get("CHAT_WORKER_URL", "https://tft-ai-coach.besirsecilmis.workers.dev").strip(),
        },
    }

    builder = DashboardBuilder()
    paths = builder.build_all(full_report)
    print(f"[Dashboard] Generated: {paths['index_html']}")

    rag_paths = RAGBuilder(full_report).write_all()
    print(f"[AI Knowledge Base] Generated: {', '.join(p.name for p in rag_paths.values())}")

    gh_step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_step_summary:
        with open(gh_step_summary, "a", encoding="utf-8") as f:
            f.write(paths["step_summary"].read_text(encoding="utf-8") + "\n")

    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if discord_webhook:
        sent = MetaSynthesizer.send_discord_webhook(discord_webhook, full_report)
        print(f"[Discord Webhook] Sent: {sent}")

    save_state({
        "updated_at": now_str,
        "ddragon_version": versions.get("ddragon_version", ""),
        "previous_cdragon": versions["previous_cdragon"],
        "latest_cdragon": versions["latest_cdragon"],
        "previous_label": versions["previous_label"],
        "latest_label": versions["latest_label"],
        "pbe_label": versions["pbe_label"],
        "pbe_set_number": pbe_set_num,
        "latest_fingerprint": latest_fp,
        "pbe_fingerprint": pbe_fp,
        "riot_api_verified": live_meta["riot_api_active"],
        "riot_official_key_connected": bool(riot_telemetry.get("connected")),
    })

    return full_report


def main() -> None:
    parser = argparse.ArgumentParser(description="TFT Set 18 Meta & Patch Intelligence Pipeline")
    parser.add_argument("--check-only", action="store_true", help="Check if Set 18 live/PBE data or Master+ meta needs update")
    parser.add_argument("--force", action="store_true", help="Force full analysis and dashboard generation")
    args = parser.parse_args()
    run_pipeline(check_only=args.check_only, force=args.force)


if __name__ == "__main__":
    main()
