"""
AI Knowledge Base (RAG) Generator for TFT Set 18.

Turns the pipeline's `full_report` into three LLM-friendly artifacts:

- `docs/llms.txt`            Short index following the llms.txt proposal (https://llmstxt.org)
- `docs/llms-full.txt`       Complete, token-efficient Markdown knowledge base for the current patch
- `docs/api/rag_context.json` Retrieval chunks (id / type / title / keywords / text) used by the
                              AI Coach chatbot (Cloudflare Worker) and any external RAG pipeline

All artifacts are regenerated on every pipeline run and attached to GitHub patch releases,
so every release doubles as a versioned, patch-pinned knowledge base.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs"
API_DIR = DOCS_DIR / "api"

SITE_URL = "https://apexq.github.io/TFT-Meta-Patch-Telemetry/"
REPO_URL = "https://github.com/Apexq/TFT-Meta-Patch-Telemetry"
RAG_SCHEMA_VERSION = 1

ATTRIBUTION = (
    "Master+ match clustering, leaderboards and item telemetry courtesy of MetaTFT.com "
    "(used with permission). Patch data via CommunityDragon and the Riot Games API. "
    "Not endorsed by Riot Games."
)


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics (Turkish-safe) for keyword matching."""
    text = (text or "").replace("İ", "i").replace("I", "ı").lower()
    text = text.replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _keywords(*parts: Any) -> List[str]:
    """Builds a de-duplicated, normalized keyword list from names/traits/items in TR & EN."""
    seen: List[str] = []
    for part in parts:
        values: Iterable[Any] = part if isinstance(part, (list, tuple, set)) else [part]
        for val in values:
            if not val:
                continue
            norm = _normalize(str(val)).strip()
            if norm and norm not in seen:
                seen.append(norm)
            for token in re.findall(r"[a-z0-9']{3,}", norm):
                if token not in seen:
                    seen.append(token)
    return seen


def _fmt_items(items: List[Dict[str, Any]]) -> str:
    return " + ".join(
        f"{i.get('name_en') or i.get('name')}" + (f" ({i['name']})" if i.get("name") and i.get("name") != i.get("name_en") else "")
        for i in items
    )


class RAGBuilder:
    """Generates llms.txt, llms-full.txt and rag_context.json from the pipeline report."""

    def __init__(self, report: Dict[str, Any]) -> None:
        self.report = report
        self.v = report.get("versions", {})
        self.patch = self.v.get("latest_label", "?")

    # ------------------------------------------------------------------ #
    # Chunks                                                              #
    # ------------------------------------------------------------------ #
    def build_chunks(self) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        chunks.append(self._overview_chunk())
        chunks.extend(self._comp_chunks())
        chunks.extend(self._unit_tier_chunks())
        chunks.extend(self._item_tier_chunks())
        chunks.extend(self._champion_diff_chunks())
        chunks.extend(self._trait_diff_chunks())
        chunks.extend(self._leaderboard_chunks())
        chunks.append(self._pbe_chunk())
        return chunks

    def _overview_chunk(self) -> Dict[str, Any]:
        r, v = self.report, self.v
        ai = r.get("ai_summary", {})
        lm = r.get("live_meta", {})
        counts = r.get("live_diff", {}).get("summary_counts", {})
        comps = lm.get("compositions", [])
        top = [c.get("comp_name_en") or c.get("comp_name") for c in comps if c.get("tier") == "S"][:6]
        text = (
            f"TFT Set 18 live patch {v.get('latest_label')} (previous {v.get('previous_label')}, "
            f"PBE {v.get('pbe_label')}, game version {v.get('ddragon_version')}). "
            f"Data generated {r.get('generated_at')}. "
            f"{lm.get('matches_analyzed', 0):,} Master+ matches analyzed, {lm.get('total_comps', len(comps))} compositions tracked. "
            f"Patch changes: {counts.get('buffed_champions', 0)} champions buffed, {counts.get('nerfed_champions', 0)} nerfed, "
            f"{counts.get('buffed_traits', 0)} traits buffed, {counts.get('nerfed_traits', 0)} nerfed. "
            f"S-tier comps: {', '.join(top) if top else 'none'}. "
            f"Summary: {ai.get('live_headline_en') or ai.get('live_headline', '')} "
            f"{ai.get('live_analysis_en') or ai.get('live_analysis', '')}"
        )
        return {
            "id": "overview",
            "type": "overview",
            "title": f"Patch {self.patch} overview",
            "keywords": _keywords("meta", "patch", "yama", "overview", "ozet", "set 18", self.patch),
            "always_include": True,
            "text": text.strip(),
        }

    def _comp_chunks(self) -> List[Dict[str, Any]]:
        out = []
        for c in self.report.get("live_meta", {}).get("compositions", []):
            st = c.get("master_stats", {})
            units = c.get("units", [])
            unit_str = ", ".join(
                f"{u.get('name_en') or u.get('name')} ({u.get('cost')}g{', carry' if u.get('is_carry') else ''}{', 3-star' if u.get('is_three_star') else ''})"
                for u in units
            )
            builds = "; ".join(
                f"{b.get('unit_name_en') or b.get('unit_name')}: {_fmt_items(b.get('items', []))}"
                for b in c.get("carry_builds", [])
            )
            schedule = "; ".join(
                f"{s.get('stage')} {s.get('level')} ({s.get('note_en')})" for s in c.get("level_schedule", [])
            )
            early = ", ".join(u.get("name_en") or u.get("name", "") for u in c.get("early_units", []))
            buffs = (c.get("buffed_units_en") or c.get("buffed_units") or []) + (c.get("buffed_traits_en") or c.get("buffed_traits") or [])
            nerfs = (c.get("nerfed_units_en") or c.get("nerfed_units") or []) + (c.get("nerfed_traits_en") or c.get("nerfed_traits") or [])
            name_en = c.get("comp_name_en") or c.get("comp_name")
            text = (
                f"[{c.get('tier')} Tier comp] {name_en} (TR: {c.get('comp_name')}). "
                f"Playstyle: {c.get('levelling')}, {c.get('unit_count')} units. "
                f"Traits: {', '.join(c.get('active_traits_en') or c.get('active_traits') or [])}. "
                f"Units: {unit_str}. "
                f"Carry BiS items: {builds or '-'}. "
                f"Master+ stats: avg placement #{st.get('avg_placement')}, top4 {st.get('top4_rate')}%, "
                f"win {st.get('win_rate')}%, {st.get('sample_size', 0):,} games. "
                f"Patch trend: {c.get('meta_status_en') or c.get('meta_status')} ({c.get('comp_delta_score', 0):+.1f})"
                f"{'; buffed: ' + ', '.join(buffs) if buffs else ''}{'; nerfed: ' + ', '.join(nerfs) if nerfs else ''}. "
                f"Leveling: {schedule or '-'}. "
                f"Stage 2 opener: {early or '-'}. "
                f"Official in-game Team Planner import code: {c.get('team_planner_code', '-')}"
            )
            item_names = [i.get("name") for b in c.get("carry_builds", []) for i in b.get("items", [])]
            item_names += [i.get("name_en") for b in c.get("carry_builds", []) for i in b.get("items", [])]
            out.append({
                "id": f"comp:{c.get('cluster_id')}",
                "type": "composition",
                "title": f"{name_en} ({c.get('tier')} tier)",
                "tier": c.get("tier"),
                "team_planner_code": c.get("team_planner_code"),
                "keywords": _keywords(
                    "comp", "kompozisyon", "takim", "build", name_en, c.get("comp_name"),
                    c.get("active_traits"), c.get("active_traits_en"),
                    [u.get("name") for u in units], [u.get("name_en") for u in units],
                    item_names, c.get("levelling"), f"{c.get('tier')} tier",
                ),
                "text": text,
            })
        return out

    def _unit_tier_chunks(self) -> List[Dict[str, Any]]:
        out = []
        for u in self.report.get("tier_lists", {}).get("unit_tiers", []):
            name_en = u.get("name_en") or u.get("name")
            status = u.get("patch_status", "UNCHANGED")
            impact = f" ({u.get('patch_impact', 0):+.1f})" if status != "UNCHANGED" else ""
            text = (
                f"[Champion] {name_en} (TR: {u.get('name')}), {u.get('cost')}-cost, traits: {', '.join(u.get('traits', []))}. "
                f"Tier {u.get('tier')} — Master+ avg placement #{u.get('avg_place')}, play rate {u.get('pick_rate')}%, "
                f"{u.get('games', 0):,} games. Patch {self.patch} status: {status}{impact}. "
                f"Best items: {_fmt_items(u.get('best_items', [])) or '-'}."
            )
            out.append({
                "id": f"unit:{u.get('apiName')}",
                "type": "champion",
                "title": f"{name_en} ({u.get('tier')} tier champion)",
                "keywords": _keywords("champion", "sampiyon", "unit", name_en, u.get("name"), u.get("traits"),
                                      [i.get("name") for i in u.get("best_items", [])],
                                      [i.get("name_en") for i in u.get("best_items", [])]),
                "text": text,
            })
        return out

    def _item_tier_chunks(self) -> List[Dict[str, Any]]:
        out = []
        for it in self.report.get("tier_lists", {}).get("item_tiers", []):
            name_en = it.get("name_en") or it.get("name")
            holders = ", ".join(h.get("name_en") or h.get("name", "") for h in it.get("holders", []))
            text = (
                f"[Item] {name_en} (TR: {it.get('name')}){' — emblem' if it.get('is_emblem') else ''}. "
                f"Tier {it.get('tier')} — Master+ avg placement #{it.get('avg_place')}, play rate {it.get('pick_rate')}%, "
                f"{it.get('games', 0):,} games. Best holders: {holders or '-'}."
            )
            out.append({
                "id": f"item:{it.get('apiName')}",
                "type": "item",
                "title": f"{name_en} ({it.get('tier')} tier item)",
                "keywords": _keywords("item", "esya", name_en, it.get("name"),
                                      [h.get("name") for h in it.get("holders", [])],
                                      [h.get("name_en") for h in it.get("holders", [])]),
                "text": text,
            })
        return out

    def _champion_diff_chunks(self) -> List[Dict[str, Any]]:
        out = []
        ld = self.report.get("live_diff", {})
        for ch in ld.get("champion_diffs", []):
            name_en = ch.get("name_en") or ch.get("name")
            changes = "; ".join(
                f"{c.get('label_en') or c.get('label')}: {c.get('old')} -> {c.get('new')} ({c.get('delta_pct', 0):+.1f}%, {c.get('type')})"
                for c in ch.get("changes", [])
            )
            text = (
                f"[Patch change {ld.get('old_patch')} -> {ld.get('new_patch')}] {name_en} (TR: {ch.get('name')}), "
                f"{ch.get('cost')}-cost: {ch.get('status')} (impact {ch.get('impact_score', 0):+.1f}). Changes: {changes}."
            )
            out.append({
                "id": f"diff:champion:{ch.get('apiName')}",
                "type": "patch_change",
                "title": f"{name_en} {ch.get('status')} in {ld.get('new_patch')}",
                "keywords": _keywords("buff", "nerf", "patch", "yama", "degisiklik", name_en, ch.get("name"), ch.get("traits"), ch.get("status")),
                "text": text,
            })
        return out

    def _trait_diff_chunks(self) -> List[Dict[str, Any]]:
        out = []
        ld = self.report.get("live_diff", {})
        for tr in ld.get("trait_diffs", []):
            name_en = tr.get("name_en") or tr.get("name")
            changes = "; ".join(f"{c.get('label_en') or c.get('label')}: {c.get('old')} -> {c.get('new')}" for c in tr.get("changes", []))
            out.append({
                "id": f"diff:trait:{tr.get('apiName')}",
                "type": "patch_change",
                "title": f"{name_en} trait {tr.get('status')} in {ld.get('new_patch')}",
                "keywords": _keywords("trait", "sinerji", "ozellik", "buff", "nerf", name_en, tr.get("name"), tr.get("status")),
                "text": (
                    f"[Trait change {ld.get('old_patch')} -> {ld.get('new_patch')}] {name_en} (TR: {tr.get('name')}): "
                    f"{tr.get('status')} (impact {tr.get('impact_score', 0):+.1f}). Changes: {changes}."
                ),
            })
        return out

    def _leaderboard_chunks(self) -> List[Dict[str, Any]]:
        out = []
        for reg in self.report.get("leaderboards", {}).get("regions", []):
            top = "; ".join(
                f"#{p.get('rank')} {p.get('riot_id')} {p.get('lp')} LP (avg #{p.get('avg_place')}, {p.get('playstyle_en')})"
                for p in reg.get("players", [])[:10]
            )
            out.append({
                "id": f"leaderboard:{reg.get('id')}",
                "type": "leaderboard",
                "title": f"{reg.get('code')} Challenger leaderboard",
                "keywords": _keywords("leaderboard", "liderlik", "challenger", "grandmaster", "cutoff", "baraj", "lp",
                                      reg.get("code"), reg.get("name_en"), reg.get("name_tr"), reg.get("id")),
                "text": (
                    f"[Leaderboard {reg.get('code')} / {reg.get('name_en')}] Challenger cutoff {reg.get('challenger_cutoff')} LP "
                    f"({reg.get('challenger_slots')} slots), Grandmaster cutoff {reg.get('grandmaster_cutoff')} LP "
                    f"({reg.get('grandmaster_slots')} slots), Master+ population {reg.get('master_population')}. "
                    f"Top 10: {top}."
                ),
            })
        return out

    def _pbe_chunk(self) -> Dict[str, Any]:
        ai = self.report.get("ai_summary", {})
        pd = self.report.get("pbe_diff", {})
        changed = [
            f"{c.get('name_en') or c.get('name')} {c.get('status')}"
            for c in pd.get("champion_diffs", []) + pd.get("trait_diffs", [])
        ]
        return {
            "id": "pbe",
            "type": "pbe",
            "title": f"PBE preview {self.v.get('pbe_label')}",
            "keywords": _keywords("pbe", "next patch", "gelecek yama", "upcoming", self.v.get("pbe_label")),
            "text": (
                f"[PBE {self.v.get('pbe_label')}] {ai.get('pbe_headline_en') or ai.get('pbe_headline', '')} "
                f"{ai.get('pbe_analysis_en') or ai.get('pbe_analysis', '')} "
                f"Changes on PBE: {', '.join(changed) if changed else 'none detected'}. "
                f"PBE data is unreleased and may change before going live."
            ).strip(),
        }

    # ------------------------------------------------------------------ #
    # Markdown artifacts                                                  #
    # ------------------------------------------------------------------ #
    def build_llms_txt(self) -> str:
        v = self.v
        return "\n".join([
            "# TFT Set 18 Meta & Patch Telemetry",
            "",
            f"> Automatically updated Teamfight Tactics Set 18 knowledge base for live patch {v.get('latest_label')} "
            f"(PBE {v.get('pbe_label')}). Master+ compositions, carry best-in-slot items, item and champion tier lists, "
            f"CommunityDragon patch diffs, regional Challenger leaderboards and official in-game Team Planner codes. "
            f"Last generated: {self.report.get('generated_at')}.",
            "",
            f"Attribution: {ATTRIBUTION}",
            "",
            "## Knowledge Base",
            "",
            f"- [Full knowledge base (Markdown)]({SITE_URL}llms-full.txt): Every composition, champion, item, patch change and leaderboard cutoff for the current patch in one file",
            f"- [RAG chunks (JSON)]({SITE_URL}api/rag_context.json): Pre-chunked retrieval documents with keywords (TR + EN names)",
            f"- [Raw report (JSON)]({SITE_URL}meta_report.json): Complete structured pipeline output",
            "",
            "## Optional",
            "",
            f"- [Interactive dashboard]({SITE_URL}): Bilingual (TR / EN) web dashboard",
            f"- [Patch release archive]({REPO_URL}/releases): Versioned, patch-pinned snapshots of the knowledge base",
            f"- [Source code]({REPO_URL}): Python pipeline orchestrated by GitHub Actions",
            "",
        ])

    def build_llms_full_txt(self, chunks: List[Dict[str, Any]]) -> str:
        v = self.v
        sections = [
            ("overview", "Patch Overview"),
            ("composition", "Master+ Meta Compositions"),
            ("patch_change", f"Patch Changes ({v.get('previous_label')} -> {v.get('latest_label')})"),
            ("champion", "Champion Tier List"),
            ("item", "Item Tier List"),
            ("leaderboard", "Regional Challenger Leaderboards"),
            ("pbe", "PBE Preview"),
        ]
        lines = [
            f"# TFT Set 18 Knowledge Base — Patch {v.get('latest_label')}",
            "",
            f"Generated: {self.report.get('generated_at')} | Live: {v.get('latest_label')} | Previous: {v.get('previous_label')} | PBE: {v.get('pbe_label')}",
            f"Source: {SITE_URL}",
            f"Attribution: {ATTRIBUTION}",
            "",
            "Notes for AI systems: Statistics are aggregated Master+ ranked data and reflect only this patch. "
            "Team Planner codes (format `02` + 10x3 hex + `TFTSet18`) can be pasted into the in-game TFT Team Planner.",
            "",
        ]
        for type_key, heading in sections:
            group = [c for c in chunks if c["type"] == type_key]
            if not group:
                continue
            lines.append(f"## {heading}")
            lines.append("")
            for c in group:
                lines.append(f"- {c['text']}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Writer                                                              #
    # ------------------------------------------------------------------ #
    def write_all(self) -> Dict[str, Path]:
        API_DIR.mkdir(parents=True, exist_ok=True)
        chunks = self.build_chunks()

        rag_payload = {
            "schema_version": RAG_SCHEMA_VERSION,
            "generated_at": self.report.get("generated_at"),
            "set_number": self.report.get("set_number", 18),
            "versions": self.v,
            "source": SITE_URL,
            "attribution": ATTRIBUTION,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

        rag_path = API_DIR / "rag_context.json"
        rag_path.write_text(json.dumps(rag_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        llms_path = DOCS_DIR / "llms.txt"
        llms_path.write_text(self.build_llms_txt(), encoding="utf-8")

        llms_full_path = DOCS_DIR / "llms-full.txt"
        llms_full_path.write_text(self.build_llms_full_txt(chunks), encoding="utf-8")

        return {"rag_context": rag_path, "llms_txt": llms_path, "llms_full_txt": llms_full_path}
