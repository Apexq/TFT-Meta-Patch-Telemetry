"""
Retrieval and Generative UI Card services for TFT Set 18 AI Coach.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from apps.telemetry.models import PatchSnapshot, RAGChunk


def normalize_query(text: str) -> str:
    """Normalize query for Turkish-friendly keyword matching."""
    if not text:
        return ""
    t = text.replace("İ", "i").replace("I", "ı").replace("ı", "i")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


class TelemetryRAGService:
    """
    RAG chunk retrieval & generative UI card extraction service.
    """

    CACHE_KEY_ACTIVE_CHUNKS = "tft_rag_active_chunks_v2"
    CACHE_TTL_SECONDS = 600  # 10 minutes

    @classmethod
    def get_active_snapshot(cls) -> Optional[PatchSnapshot]:
        return PatchSnapshot.objects.filter(is_active=True).first()

    @classmethod
    def get_cached_chunks(cls, snapshot: Optional[PatchSnapshot] = None) -> List[Dict[str, Any]]:
        cached = cache.get(cls.CACHE_KEY_ACTIVE_CHUNKS)
        if cached:
            return cached

        active_snap = snapshot or cls.get_active_snapshot()
        if not active_snap:
            return []

        chunks = list(
            active_snap.chunks.values(
                "chunk_id",
                "chunk_type",
                "title_tr",
                "title_en",
                "keywords_normalized",
                "content_text",
                "ui_card_payload",
            )
        )
        cache.set(cls.CACHE_KEY_ACTIVE_CHUNKS, chunks, cls.CACHE_TTL_SECONDS)
        return chunks

    @classmethod
    def invalidate_cache(cls) -> None:
        cache.delete(cls.CACHE_KEY_ACTIVE_CHUNKS)

    @classmethod
    def retrieve_chunks_and_cards(
        cls,
        query: str,
        top_k: int = 8,
        preferred_lang: str = "tr",
        selected_items: Optional[List[str]] = None,
        history_text: str = "",
        mode: str = "META_COACH",
    ) -> Dict[str, Any]:
        """
        Retrieves top relevant RAG chunks and extracts candidate Generative UI cards
        with deterministic card_id values so the LLM can decide which cards to show.
        """
        combined_query = f"{query} {history_text}".strip() if history_text else query
        norm_query = normalize_query(combined_query)
        q_tokens = [w for w in norm_query.split() if len(w) > 1]
        chunks = cls.get_cached_chunks()

        if not chunks:
            return {"chunks": [], "ui_cards": [], "cited_chunk_ids": []}

        STOPWORDS = {"en", "ve", "ile", "bir", "de", "da", "bu", "ne", "mi", "mu", "var", "miyiz", "icin", "nasil", "hangisi", "hangileri", "the", "and", "or", "in", "of", "to", "a", "is", "peki", "neleri", "erken", "2"}
        meaningful_tokens = [w for w in q_tokens if w not in STOPWORDS]
        if not meaningful_tokens:
            meaningful_tokens = q_tokens

        scored = []
        overview_chunks = []
        for ch in chunks:
            if ch["chunk_type"] == "overview":
                overview_chunks.append(ch)
                continue

            score = 0.0
            kw_text = ch["keywords_normalized"]
            content = ch["content_text"].lower()

            for tok in meaningful_tokens:
                # Direct match or root match
                if tok in kw_text or (len(tok) >= 4 and tok[:4] in kw_text):
                    score += 6.0
                elif tok in content:
                    score += 2.0

            # Comp / Hero / Unit generic query boosters
            if any(w in norm_query for w in ("comp", "komp", "hero", "sampiyon", "birim", "tahta", "erken", "level", "2 le", "2le", "desteler")):
                if ch["chunk_type"] == "composition":
                    score += 10.0
                elif ch["chunk_type"] == "champion":
                    score += 4.0

            # Item component query booster
            if selected_items and ch["chunk_type"] == "composition":
                payload = ch.get("ui_card_payload") or {}
                comp_items = payload.get("comp_item_ids", [])
                for it in selected_items:
                    if it in comp_items or it.lower() in kw_text:
                        score += 8.0

            # Round tag booster (e.g. 2-1, 3-2, 4-2)
            for rnd in ("2-1", "3-2", "4-2"):
                if rnd in norm_query and rnd in kw_text:
                    score += 6.0

            # Charm / encounter / augment / PBE boosters
            if any(k in norm_query for k in ("tilsim", "charm")) and ch["chunk_type"] == "charm":
                score += 7.0
            if any(k in norm_query for k in ("portal", "karsilasma", "encounter")) and ch["chunk_type"] == "encounter":
                score += 7.0
            if any(k in norm_query for k in ("eklenti", "augment")) and ch["chunk_type"] == "augment":
                score += 7.0
            if (
                mode == "PBE_SCOUT"
                or any(k in norm_query for k in ("pbe", "set 19", "set19", "19 1", "yeni set", "next set"))
            ) and ch["chunk_type"] == "pbe":
                score += 14.0

            if score > 0:
                scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = [item[1] for item in scored[:top_k]]

        # Always include overview chunk (just like worker/src/index.js always_include)
        for ov in overview_chunks[:1]:
            if ov not in top_results:
                top_results.insert(0, ov)

        # Build candidate UI cards with unique card_id so the AI can choose which to display
        ui_cards = []
        seen_card_keys = set()
        for c in top_results:
            payload = c.get("ui_card_payload")
            if payload and payload.get("card_type"):
                card_key = f"{payload.get('card_type')}:{payload.get('comp_name') or payload.get('title') or c['chunk_id']}"
                if card_key not in seen_card_keys:
                    seen_card_keys.add(card_key)
                    card_copy = dict(payload)
                    card_copy["card_id"] = str(c["chunk_id"])
                    ui_cards.append(card_copy)

        return {
            "chunks": top_results,
            "ui_cards": ui_cards[:4],
            "cited_chunk_ids": [c["chunk_id"] for c in top_results if c.get("chunk_id")],
        }


def sync_telemetry_payload(report_data: Dict[str, Any], rag_payload: Any) -> Dict[str, Any]:
    """
    Atomically synchronizes meta_report.json and rag_context.json payloads into
    PatchSnapshot and RAGChunk tables with Generative UI card attachments.
    Shared by both `manage.py sync_tft_meta` and `POST /api/telemetry/sync/`.
    """
    from django.db import transaction

    rag_chunks_raw = rag_payload.get("chunks", []) if isinstance(rag_payload, dict) else (rag_payload or [])

    versions = report_data.get("versions", {})
    patch_label = versions.get("latest_label", "18.6")
    previous_label = versions.get("previous_label", "18.5")
    pbe_label = versions.get("pbe_label", "18.7")
    cdragon_version = report_data.get("cdragon_version", "16.22")
    fingerprint = report_data.get("fingerprint") or report_data.get("set18_fingerprint") or f"snap-{patch_label}"
    matches_analyzed = report_data.get("live_meta", {}).get("matches_analyzed", 0)

    comps_by_id = {c.get("cluster_id"): c for c in report_data.get("live_meta", {}).get("compositions", [])}
    augments_by_id = {a.get("apiName"): a for a in report_data.get("augments", {}).get("augments", [])}
    encounters_by_id = {e.get("apiName"): e for e in report_data.get("mechanics", {}).get("encounters", [])}
    charms_by_id = {c.get("apiName"): c for c in report_data.get("mechanics", {}).get("charms", [])}
    pbe_preview = report_data.get("pbe_preview") or {}
    pbe_meta = report_data.get("pbe_meta") or {}

    pbe_card_payload: Dict[str, Any] = {}
    if pbe_preview and pbe_preview.get("champions"):
        five_costs = [
            {
                "name": c.get("name"),
                "name_en": c.get("name_en") or c.get("name"),
                "cost": c.get("cost", 5),
                "traits": c.get("traits", []),
                "traits_en": c.get("traits_en") or c.get("traits", []),
                "icon": c.get("icon", ""),
            }
            for c in pbe_preview.get("champions", [])
            if int(c.get("cost") or 0) == 5
        ][:10]
        pbe_card_payload = {
            "card_type": "pbe_preview",
            "title": f"Set {pbe_preview.get('set_number', 19)} PBE ({pbe_label})",
            "set_number": pbe_preview.get("set_number", 19),
            "pbe_label": pbe_label,
            "source": pbe_preview.get("source", "MetaTFT PBE"),
            "total_champions": pbe_preview.get("total_champions", len(pbe_preview.get("champions", []))),
            "total_traits": pbe_preview.get("total_traits", len(pbe_preview.get("traits", []))),
            "champions_5g": five_costs,
            "top_traits": [
                {
                    "name": t.get("name"),
                    "name_en": t.get("name_en") or t.get("name"),
                    "breakpoints": t.get("breakpoints", []),
                    "icon": t.get("icon", ""),
                }
                for t in pbe_preview.get("traits", [])[:8]
            ],
            "early_comps": [
                {
                    "comp_name": comp.get("comp_name"),
                    "comp_name_en": comp.get("comp_name_en") or comp.get("comp_name"),
                    "tier": comp.get("tier", "PBE"),
                    "units": (comp.get("units") or [])[:6],
                }
                for comp in (pbe_meta.get("compositions") or [])[:3]
            ],
        }

    with transaction.atomic():
        PatchSnapshot.objects.filter(is_active=True).update(is_active=False)

        snapshot, created = PatchSnapshot.objects.update_or_create(
            patch_label=patch_label,
            fingerprint=fingerprint,
            defaults={
                "previous_label": previous_label,
                "pbe_label": pbe_label,
                "cdragon_version": cdragon_version,
                "is_active": True,
                "matches_analyzed": matches_analyzed,
                "full_report_json": report_data,
            },
        )

        snapshot.chunks.all().delete()

        chunk_objects = []
        for item in rag_chunks_raw:
            chunk_id = item.get("id", "")
            chunk_type = item.get("type", "overview")
            title = item.get("title", "")
            keywords = item.get("keywords", "")
            content_text = item.get("text", "")

            ui_card_payload: Dict[str, Any] = {}

            if chunk_type == "composition":
                raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                comp = comps_by_id.get(raw_id)
                if comp:
                    ui_card_payload = {
                        "card_type": "composition",
                        "cluster_id": comp.get("cluster_id"),
                        "comp_name": comp.get("comp_name"),
                        "comp_name_en": comp.get("comp_name_en") or comp.get("comp_name"),
                        "tier": comp.get("tier"),
                        "levelling": comp.get("levelling"),
                        "meta_status": comp.get("meta_status"),
                        "comp_delta_score": comp.get("comp_delta_score", 0.0),
                        "active_traits": comp.get("active_traits", []),
                        "active_traits_en": comp.get("active_traits_en", []),
                        "avg_placement": comp.get("master_stats", {}).get("avg_placement", 4.5),
                        "top4_rate": comp.get("master_stats", {}).get("top4_rate", 50.0),
                        "win_rate": comp.get("master_stats", {}).get("win_rate", 12.5),
                        "team_planner_code": comp.get("team_planner_code", ""),
                        "comp_item_ids": comp.get("comp_item_ids", []),
                        "units": comp.get("units", [])[:10],
                        "carry_builds": comp.get("carry_builds", []),
                        "board_grid": comp.get("board_grid", []),
                        "level_schedule": comp.get("level_schedule", []),
                    }

            elif chunk_type == "augment":
                raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                aug = augments_by_id.get(raw_id)
                if aug:
                    ui_card_payload = {
                        "card_type": "augment",
                        "apiName": aug.get("apiName"),
                        "name": aug.get("name"),
                        "name_en": aug.get("name_en"),
                        "tier": aug.get("tier"),
                        "tier_color": aug.get("tier_color", "#f0c374"),
                        "rarity": aug.get("rarity"),
                        "rarity_tr": aug.get("rarity_tr"),
                        "rounds": aug.get("rounds", []),
                        "tags": aug.get("tags", []),
                        "desc": aug.get("desc"),
                        "desc_en": aug.get("desc_en"),
                        "icon": aug.get("icon"),
                        "synergy_comps": aug.get("synergy_comps", []),
                    }

            elif chunk_type == "encounter":
                raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                enc = encounters_by_id.get(raw_id)
                if enc:
                    ui_card_payload = {
                        "card_type": "encounter",
                        "apiName": enc.get("apiName"),
                        "name": enc.get("name"),
                        "name_en": enc.get("name_en"),
                        "category": enc.get("category"),
                        "category_en": enc.get("category_en"),
                        "tempo_rating": enc.get("tempo_rating"),
                        "tempo_rating_en": enc.get("tempo_rating_en"),
                        "tempo_color": enc.get("tempo_color", "#a855f7"),
                        "post_spawn": enc.get("post_spawn"),
                        "post_spawn_en": enc.get("post_spawn_en"),
                        "strategy_tr": enc.get("strategy_tr"),
                        "strategy_en": enc.get("strategy_en"),
                        "synergy_comps_tr": enc.get("synergy_comps_tr", []),
                        "synergy_comps_en": enc.get("synergy_comps_en", []),
                    }

            elif chunk_type == "charm":
                raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                chm = charms_by_id.get(raw_id)
                if chm:
                    ui_card_payload = {
                        "card_type": "charm",
                        "apiName": chm.get("apiName"),
                        "name": chm.get("name"),
                        "name_en": chm.get("name_en"),
                        "cost": chm.get("cost"),
                        "tier": chm.get("tier"),
                        "category": chm.get("category"),
                        "category_tr": chm.get("category_tr"),
                        "stages": chm.get("stages"),
                        "desc": chm.get("desc"),
                        "desc_en": chm.get("desc_en"),
                        "rec_tr": chm.get("rec_tr"),
                        "rec_en": chm.get("rec_en"),
                    }

            elif chunk_type == "pbe" and pbe_card_payload:
                ui_card_payload = pbe_card_payload

            chunk_objects.append(
                RAGChunk(
                    snapshot=snapshot,
                    chunk_id=chunk_id,
                    chunk_type=chunk_type,
                    title_tr=title,
                    title_en=title,
                    keywords_normalized=keywords,
                    content_text=content_text,
                    ui_card_payload=ui_card_payload,
                )
            )

        RAGChunk.objects.bulk_create(chunk_objects, batch_size=200)
        TelemetryRAGService.invalidate_cache()

    return {
        "snapshot": snapshot,
        "created": created,
        "patch_label": patch_label,
        "pbe_label": pbe_label,
        "fingerprint": fingerprint,
        "chunks_synced": len(chunk_objects),
    }
