"""
Static Dashboard & GitHub Step Summary Generator for TFT Set 18.
Renders `docs/index.html` using Jinja2 + Tailwind CSS and writes `docs/STEP_SUMMARY.md`
for `$GITHUB_STEP_SUMMARY` in GitHub Actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"
DOCS_DIR = ROOT_DIR / "docs"


class DashboardBuilder:
    """Builds the GitHub Pages static site and GitHub Actions Job Summary."""

    def __init__(self) -> None:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def build_all(self, full_report: Dict[str, Any]) -> Dict[str, Path]:
        template = self.env.get_template("index.html.j2")
        html_content = template.render(report=full_report)
        index_path = DOCS_DIR / "index.html"
        index_path.write_text(html_content, encoding="utf-8")

        json_path = DOCS_DIR / "meta_report.json"
        json_path.write_text(json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8")

        nojekyll_path = DOCS_DIR / ".nojekyll"
        nojekyll_path.write_text("", encoding="utf-8")

        summary_md = self.build_step_summary_markdown(full_report)
        summary_path = DOCS_DIR / "STEP_SUMMARY.md"
        summary_path.write_text(summary_md, encoding="utf-8")

        return {
            "index_html": index_path,
            "json_report": json_path,
            "step_summary": summary_path,
        }

    @staticmethod
    def build_step_summary_markdown(report: Dict[str, Any]) -> str:
        v = report["versions"]
        live_diff = report["live_diff"]
        live_meta = report["live_meta"]
        ai = report["ai_summary"]

        lines = [
            f"# TFT Set 18 Patch & Meta Report ({v['previous_label']} -> {v['latest_label']})",
            "",
            f"**Data Source:** {live_meta.get('data_source_en') or live_meta['data_source']}",
            "",
            "### Executive Summary (EN)",
            f"**{ai.get('live_headline_en') or ai['live_headline']}**",
            f"{ai.get('live_analysis_en') or ai['live_analysis']}",
            "",
            "### Özet Rapor (TR)",
            f"**{ai['live_headline']}**",
            f"{ai['live_analysis']}",
            "",
            "## Set 18 Master+ Meta Compositions & Carry Best-in-Slot Items",
            "| Tier | Composition (EN / TR) | Board | Carry BiS Items | Patch Delta | Avg Place | Top 4 % | Win % | Matches |",
            "| :---: | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |",
        ]

        for comp in live_meta.get("compositions", [])[:15]:
            st = comp["master_stats"]
            name_en = comp.get("comp_name_en", comp["comp_name"])
            name_display = f"{name_en} ({comp['comp_name']})" if name_en != comp["comp_name"] else comp["comp_name"]
            cb_list = comp.get("carry_builds", [])
            if cb_list:
                cb = cb_list[0]
                items_str = ", ".join(i.get("name_en", i["name"]) for i in cb.get("items", []))
                bis_display = f"**{cb.get('unit_name_en', cb['unit_name'])}:** {items_str}"
            else:
                bis_display = "-"
            lines.append(
                f"| **{comp['tier']}** | {name_display} | `{comp.get('levelling', 'Fast 8')} ({comp.get('unit_count', 8)})` | "
                f"{bis_display} | `{comp.get('meta_status_en', comp['meta_status'])} ({comp['comp_delta_score']:+.1f})` | "
                f"**#{st['avg_placement']}** | {st['top4_rate']}% | {st['win_rate']}% | {st['sample_size']:,} |"
            )

        lines.extend([
            "",
            f"## Set 18 Champion Balance Changes ({v['previous_label']} -> {v['latest_label']})",
            "| Champion | Cost | Status | Impact Score | Stat & Ability Adjustments |",
            "| :--- | :---: | :---: | :---: | :--- |",
        ])

        for ch in live_diff.get("champion_diffs", [])[:15]:
            chg_summary = ", ".join(
                f"{c.get('label_en', c['label'])}: {c['old']} -> {c['new']}" for c in ch["changes"][:3]
            )
            lines.append(
                f"| **{ch.get('name_en', ch['name'])}** | {ch['cost']} | `{ch['status']}` | `{ch['impact_score']:+.1f}` | {chg_summary} |"
            )

        aug_data = report.get("augments", {})
        if aug_data and aug_data.get("augments"):
            lines.extend([
                "",
                "## Set 18 Top S-Tier Augments (Master+ Telemetry)",
                "| Tier | Augment (EN / TR) | Rarity | Rounds | Avg Place | Pick Rate | Top 4 % | Win % |",
                "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
            ])
            for aug in [a for a in aug_data.get("augments", []) if a.get("tier") == "S"][:10]:
                name_en = aug.get("name_en", aug["name"])
                rnds = ", ".join(aug.get("rounds", []))
                lines.append(
                    f"| **S** | {name_en} ({aug['name']}) | `{aug.get('rarity')}` | `{rnds}` | **#{aug['avg_place']}** | {aug['pick_rate']}% | {aug['top4_rate']}% | {aug['win_rate']}% |"
                )

        mech_data = report.get("mechanics", {})
        if mech_data and mech_data.get("encounters"):
            lines.extend([
                "",
                "## Set 18 Opening Encounters & Tempo Rating (20 Encounters)",
                "| Encounter (EN / TR) | Category | Tempo Rating | In-Game Rule |",
                "| :--- | :---: | :---: | :--- |",
            ])
            for enc in mech_data.get("encounters", [])[:8]:
                lines.append(
                    f"| **{enc.get('name_en', enc['name'])}** ({enc['name']}) | `{enc.get('category_en', enc['category'])}` | `{enc.get('tempo_rating_en', enc['tempo_rating'])}` | {enc.get('post_spawn_en', enc['post_spawn'])} |"
                )

        lines.extend([
            "",
            f"## PBE Early Preview ({v['pbe_label']})",
            f"**{ai.get('pbe_headline_en') or ai['pbe_headline']}**",
            "",
            f"{ai.get('pbe_analysis_en') or ai['pbe_analysis']}",
            "",
            f"*Generated at: {report['generated_at']} | Target Mutator: `TFTSet18`*",
        ])
        return "\n".join(lines)
