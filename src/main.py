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

    latest_data = tr_client.fetch_set18_data(versions["latest_cdragon"], force_refresh=check_only)
    pbe_data = tr_client.fetch_set18_data("pbe", force_refresh=check_only)

    latest_fp = CDragonClient.compute_set18_fingerprint(latest_data)
    pbe_fp = CDragonClient.compute_set18_fingerprint(pbe_data)

    prev_state = load_state()
    live_changed = (
        prev_state.get("latest_cdragon") != versions["latest_cdragon"]
        or prev_state.get("ddragon_version") != versions.get("ddragon_version")
        or prev_state.get("latest_fingerprint") != latest_fp
    )
    pbe_changed = prev_state.get("pbe_fingerprint") != pbe_fp
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
            f"(live_changed={live_changed}, pbe_changed={pbe_changed}, meta_stale={meta_stale})"
        )
        return {"should_run": should_run, "versions": versions}

    prev_data = tr_client.fetch_set18_data(versions["previous_cdragon"])

    en_client = CDragonClient(lang="en_us")
    en_latest = en_client.fetch_set18_data(versions["latest_cdragon"])
    en_champ_names = {c["apiName"]: c.get("name", c["apiName"]) for c in en_latest.get("champions", [])}
    en_trait_names = {t["apiName"]: t.get("name", t["apiName"]) for t in en_latest.get("traits", [])}
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
        en_champ_names=en_champ_names,
        en_trait_names=en_trait_names,
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

    synthesizer = MetaSynthesizer()
    ai_summary = synthesizer.generate_turkish_meta_summary(
        live_diff=live_diff,
        live_meta=live_meta,
        pbe_diff=pbe_diff,
        pbe_meta=pbe_meta,
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
        "leaderboards": leaderboards,
    }

    builder = DashboardBuilder()
    paths = builder.build_all(full_report)
    print(f"[Dashboard] Generated: {paths['index_html']}")

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
