"""
Meta Synthesizer & Executive Report Generator for TFT Set 18.
Produces bilingual (Turkish & English) meta summaries via GitHub Models API (`GITHUB_TOKEN`)
or deterministic synthesis fallback, plus optional Discord Webhook notifications.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, Optional


class MetaSynthesizer:
    """Generates bilingual (TR / EN) executive meta summaries."""

    GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com/chat/completions"

    def __init__(self, github_token: Optional[str] = None, model_name: str = "gpt-4o-mini") -> None:
        self.github_token = (github_token or os.environ.get("GITHUB_TOKEN") or "").strip()
        self.model_name = model_name

    def generate_turkish_meta_summary(
        self,
        live_diff: Dict[str, Any],
        live_meta: Dict[str, Any],
        pbe_diff: Dict[str, Any],
        pbe_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generates both Turkish and English executive summaries for the dashboard."""
        fallback = self._build_bilingual_rule_based_report(live_diff, live_meta, pbe_diff, pbe_meta)

        if not self.github_token:
            return fallback

        try:
            prompt = self._build_llm_prompt(live_diff, live_meta, pbe_diff, pbe_meta)
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a Challenger-tier Teamfight Tactics (TFT Set 18) data analyst. "
                            "Given mathematical patch diff and Master+ match statistics, produce concise, "
                            "technical executive summaries in both Turkish and English. Return ONLY valid JSON with keys: "
                            '{"live_headline": "...", "live_analysis": "...", "pbe_headline": "...", "pbe_analysis": "...", '
                            '"live_headline_en": "...", "live_analysis_en": "...", "pbe_headline_en": "...", "pbe_analysis_en": "..."}'
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.25,
                "response_format": {"type": "json_object"},
            }
            req = urllib.request.Request(
                self.GITHUB_MODELS_ENDPOINT,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.github_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "TFT-Set18-Meta-Analyzer/2.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                content = resp_data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return {
                    "engine": f"GitHub Models ({self.model_name})",
                    "engine_en": f"GitHub Models ({self.model_name})",
                    "live_headline": parsed.get("live_headline") or fallback["live_headline"],
                    "live_analysis": parsed.get("live_analysis") or fallback["live_analysis"],
                    "pbe_headline": parsed.get("pbe_headline") or fallback["pbe_headline"],
                    "pbe_analysis": parsed.get("pbe_analysis") or fallback["pbe_analysis"],
                    "live_headline_en": parsed.get("live_headline_en") or fallback["live_headline_en"],
                    "live_analysis_en": parsed.get("live_analysis_en") or fallback["live_analysis_en"],
                    "pbe_headline_en": parsed.get("pbe_headline_en") or fallback["pbe_headline_en"],
                    "pbe_analysis_en": parsed.get("pbe_analysis_en") or fallback["pbe_analysis_en"],
                }
        except Exception:
            return fallback

    def _build_llm_prompt(
        self,
        live_diff: Dict[str, Any],
        live_meta: Dict[str, Any],
        pbe_diff: Dict[str, Any],
        pbe_meta: Dict[str, Any],
    ) -> str:
        top_live_buffs = [f"{c['name_en']} (+{c['impact_score']})" for c in live_diff["champion_diffs"] if c["status"] == "BUFF"][:5]
        top_live_nerfs = [f"{c['name_en']} ({c['impact_score']})" for c in live_diff["champion_diffs"] if c["status"] == "NERF"][:5]
        top_live_comps = [
            f"{c['comp_name']} / {c['comp_name_en']} (Tier {c['tier']}, Avg Place: #{c['master_stats']['avg_placement']}, Patch Delta: {c['comp_delta_score']:+})"
            for c in live_meta["compositions"][:5]
        ]

        top_pbe_buffs = [f"{c['name_en']} (+{c['impact_score']})" for c in pbe_diff["champion_diffs"] if c["status"] == "BUFF"][:5]
        top_pbe_comps = [
            f"{c['comp_name']} / {c['comp_name_en']} (PBE Delta: {c['comp_delta_score']:+})"
            for c in pbe_meta["compositions"][:4]
        ]

        return (
            f"TFT Set 18 Live Patch ({live_diff['old_patch']} -> {live_diff['new_patch']}):\n"
            f"- Buffed Champions: {', '.join(top_live_buffs) or 'None'}\n"
            f"- Nerfed Champions: {', '.join(top_live_nerfs) or 'None'}\n"
            f"- Top Master+ Compositions: {', '.join(top_live_comps)}\n\n"
            f"TFT Set 18 PBE Patch ({pbe_diff['old_patch']} -> {pbe_diff['new_patch']}):\n"
            f"- PBE Buffs: {', '.join(top_pbe_buffs) or 'None'}\n"
            f"- PBE Impacted Comps: {', '.join(top_pbe_comps)}\n"
        )

    def _build_bilingual_rule_based_report(
        self,
        live_diff: Dict[str, Any],
        live_meta: Dict[str, Any],
        pbe_diff: Dict[str, Any],
        pbe_meta: Dict[str, Any],
    ) -> Dict[str, str]:
        buffs = [c for c in live_diff.get("champion_diffs", []) if c["status"] == "BUFF"]
        nerfs = [c for c in live_diff.get("champion_diffs", []) if c["status"] == "NERF"]
        comps = live_meta.get("compositions", [])
        rising_comps = [c for c in comps if c["meta_status"] == "YÜKSELEN"]
        falling_comps = [c for c in comps if c["meta_status"] == "DÜŞEN"]

        top_buff_tr = ", ".join(f"{c['name']} (+{c['impact_score']})" for c in buffs[:3]) or "yok"
        top_buff_en = ", ".join(f"{c.get('name_en', c['name'])} (+{c['impact_score']})" for c in buffs[:3]) or "none"
        top_nerf_tr = ", ".join(f"{c['name']} ({c['impact_score']})" for c in nerfs[:3]) or "yok"
        top_nerf_en = ", ".join(f"{c.get('name_en', c['name'])} ({c['impact_score']})" for c in nerfs[:3]) or "none"

        top_tier_comp = comps[0] if comps else {"comp_name": "Set 18 Meta", "comp_name_en": "Set 18 Meta", "master_stats": {"avg_placement": 4.1}}
        best_rising = rising_comps[0] if rising_comps else top_tier_comp
        worst_falling = falling_comps[0] if falling_comps else None

        # Turkish Live Summary
        live_headline_tr = (
            f"Set 18 ({live_diff['new_patch']}) Master+ Metasında '{top_tier_comp['comp_name']}' (#{top_tier_comp['master_stats']['avg_placement']}) "
            f"ve '{best_rising['comp_name']}' Öne Çıkıyor"
        )
        live_analysis_tr = (
            f"{live_meta.get('matches_analyzed', 0):,} gerçek Challenger, Grandmaster ve Master maçı üzerinden yapılan kümeleme analizinde "
            f"'{top_tier_comp['comp_name']}' ortalama #{top_tier_comp['master_stats']['avg_placement']} sıralama ile en yüksek performansı gösteriyor. "
            f"{live_diff['old_patch']} -> {live_diff['new_patch']} yama geçişinde {live_diff['summary_counts']['total_champions_changed']} şampiyon ve "
            f"{live_diff['summary_counts']['total_traits_changed']} özellik değişti: {top_buff_tr} güçlenirken, {top_nerf_tr} zayıfladı. "
            f"Yama değişikliklerinden en çok kazanan S-Tier deste '{best_rising['comp_name']}' (+{best_rising.get('comp_delta_score', 0)}) oldu"
            + (f"; '{worst_falling['comp_name']}' ({worst_falling.get('comp_delta_score', 0)}) ise aldığı nerflere rağmen Master+ lobilerinde oynanmaya devam ediyor." if worst_falling else ".")
        )

        # English Live Summary
        live_headline_en = (
            f"Set 18 ({live_diff['new_patch']}) Master+ Meta Led by '{top_tier_comp.get('comp_name_en', top_tier_comp['comp_name'])}' "
            f"(#{top_tier_comp['master_stats']['avg_placement']}) and '{best_rising.get('comp_name_en', best_rising['comp_name'])}'"
        )
        live_analysis_en = (
            f"Across {live_meta.get('matches_analyzed', 0):,} real Challenger, Grandmaster, and Master matches, "
            f"'{top_tier_comp.get('comp_name_en', top_tier_comp['comp_name'])}' leads the meta with a #{top_tier_comp['master_stats']['avg_placement']} average placement. "
            f"In the {live_diff['old_patch']} -> {live_diff['new_patch']} patch diff, {live_diff['summary_counts']['total_champions_changed']} champions and "
            f"{live_diff['summary_counts']['total_traits_changed']} traits were adjusted: {top_buff_en} received significant buffs while {top_nerf_en} was nerfed. "
            f"'{best_rising.get('comp_name_en', best_rising['comp_name'])}' (+{best_rising.get('comp_delta_score', 0)}) gained the largest mathematical boost from the patch"
            + (f", whereas '{worst_falling.get('comp_name_en', worst_falling['comp_name'])}' ({worst_falling.get('comp_delta_score', 0)}) experienced direct trait/unit nerfs." if worst_falling else ".")
        )

        # PBE Summaries
        pbe_buffs = [c for c in pbe_diff.get("champion_diffs", []) if c["status"] == "BUFF"]
        pbe_rising = [c for c in pbe_meta.get("compositions", []) if c["comp_delta_score"] > 0]

        if not pbe_diff.get("champion_diffs") and not pbe_diff.get("trait_diffs"):
            pbe_headline_tr = f"{pbe_diff['new_patch']}: PBE Verisi Güncel Canlı Yama ({live_diff['new_patch']}) ile Senkronize"
            pbe_analysis_tr = (
                f"CommunityDragon üzerindeki PBE dalında şu an {live_diff['new_patch']} yamasından farklı bir Set 18 değişikliği bulunmuyor. "
                f"Yeni PBE güncellemesi yayınlandığında mevcut Master+ desteleri üzerindeki etkisi otomatik olarak hesaplanacaktır."
            )
            pbe_headline_en = f"{pbe_diff['new_patch']}: PBE Branch Synchronized with Live Patch ({live_diff['new_patch']})"
            pbe_analysis_en = (
                f"No numeric Set 18 differences currently exist between CommunityDragon's PBE branch and live patch {live_diff['new_patch']}. "
                f"When the next PBE cycle deploys, impact projections on existing Master+ compositions will be computed automatically."
            )
        else:
            pbe_buff_tr = ", ".join(f"{c['name']} (+{c['impact_score']})" for c in pbe_buffs[:3]) or "belirgin bir birim"
            pbe_buff_en = ", ".join(f"{c.get('name_en', c['name'])} (+{c['impact_score']})" for c in pbe_buffs[:3]) or "key units"
            pbe_top = pbe_rising[0] if pbe_rising else (pbe_meta["compositions"][0] if pbe_meta["compositions"] else top_tier_comp)

            pbe_headline_tr = f"{pbe_diff['new_patch']} Erken Bakış: '{pbe_top['comp_name']}' Destesi PBE'de Güçleniyor"
            pbe_analysis_tr = (
                f"Canlı {live_diff['new_patch']} yaması ile {pbe_diff['new_patch']} test sunucusu arasındaki CDragon JSON karşılaştırmasında "
                f"{pbe_diff['summary_counts']['total_champions_changed']} şampiyon ve {pbe_diff['summary_counts']['total_traits_changed']} özellik farkı tespit edildi. "
                f"Özellikle {pbe_buff_tr} güçlendirmeleri, mevcut Master+ destelerinden '{pbe_top['comp_name']}' kompozisyonunu gelecek yamada yukarı taşıyor. "
                f"PBE yaması canlı sunucuya çıktığında bu projeksiyon gerçek Master+ maç verileriyle doğrulanacaktır."
            )
            pbe_headline_en = f"{pbe_diff['new_patch']} Early Preview: '{pbe_top.get('comp_name_en', pbe_top['comp_name'])}' Gains Momentum on PBE"
            pbe_analysis_en = (
                f"Comparing live patch {live_diff['new_patch']} against the {pbe_diff['new_patch']} branch on CommunityDragon reveals "
                f"{pbe_diff['summary_counts']['total_champions_changed']} champion and {pbe_diff['summary_counts']['total_traits_changed']} trait adjustments. "
                f"Buffs to {pbe_buff_en} directly strengthen the '{pbe_top.get('comp_name_en', pbe_top['comp_name'])}' Master+ archetype. "
                f"Once the PBE patch reaches live servers, this projection will be finalized against live Master+ match telemetry."
            )

        return {
            "engine": "Sentez Motoru (Rule-Based + GitHub Models)",
            "engine_en": "Synthesis Engine (Rule-Based + GitHub Models)",
            "live_headline": live_headline_tr,
            "live_analysis": live_analysis_tr,
            "pbe_headline": pbe_headline_tr,
            "pbe_analysis": pbe_analysis_tr,
            "live_headline_en": live_headline_en,
            "live_analysis_en": live_analysis_en,
            "pbe_headline_en": pbe_headline_en,
            "pbe_analysis_en": pbe_analysis_en,
        }

    @staticmethod
    def send_discord_webhook(webhook_url: str, report_payload: Dict[str, Any]) -> bool:
        if not webhook_url:
            return False
        live_diff = report_payload["live_diff"]
        ai = report_payload["ai_summary"]
        top_comps = report_payload["live_meta"]["compositions"][:4]
        comp_lines = "\n".join(
            f"- **[{c['tier']}-Tier] {c['comp_name']}** (`{c['levelling']} • {c['unit_count']} Units` | Avg: `#{c['master_stats']['avg_placement']}` | Patch Delta: `{c['comp_delta_score']:+}`)"
            for c in top_comps
        )
        embed = {
            "username": "TFT Set 18 Meta Analyzer",
            "embeds": [
                {
                    "title": f"TFT Set 18 Patch & Meta Report ({live_diff['old_patch']} -> {live_diff['new_patch']})",
                    "description": ai["live_analysis"],
                    "color": 0x10B981,
                    "fields": [
                        {"name": "Top Master+ Compositions", "value": comp_lines or "No data", "inline": False},
                        {"name": "PBE Early Preview", "value": ai["pbe_headline"], "inline": False},
                    ],
                }
            ],
        }
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(embed).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "TFT-Set18-Meta-Analyzer/2.0"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False
