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
    ) -> Dict[str, Any]:
        """
        Retrieves top relevant RAG chunks and extracts matching Generative UI cards.
        """
        norm_query = normalize_query(query)
        q_tokens = [w for w in norm_query.split() if len(w) > 1]
        chunks = cls.get_cached_chunks()

        if not chunks:
            return {"chunks": [], "ui_cards": [], "cited_chunk_ids": []}

        STOPWORDS = {"en", "ve", "ile", "bir", "de", "da", "bu", "ne", "mi", "mu", "var", "miyiz", "icin", "nasil", "hangisi", "hangileri", "the", "and", "or", "in", "of", "to", "a", "is"}
        meaningful_tokens = [w for w in q_tokens if w not in STOPWORDS]
        if not meaningful_tokens:
            meaningful_tokens = q_tokens

        scored = []
        for ch in chunks:
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

            # Charm / encounter boosters
            if any(k in norm_query for k in ("tilsim", "charm")) and ch["chunk_type"] == "charm":
                score += 7.0
            if any(k in norm_query for k in ("portal", "karsilasma", "encounter")) and ch["chunk_type"] == "encounter":
                score += 7.0
            if any(k in norm_query for k in ("eklenti", "augment")) and ch["chunk_type"] == "augment":
                score += 7.0

            if score > 0:
                scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = [item[1] for item in scored[:top_k]]

        # If zero matches found, include overview chunk + top S-tier compositions
        if not top_results:
            top_results = [c for c in chunks if c["chunk_type"] == "overview"][:1]
            top_results.extend([c for c in chunks if c["chunk_type"] == "composition"][:3])

        ui_cards = []
        seen_card_keys = set()
        for c in top_results:
            payload = c.get("ui_card_payload")
            if payload and payload.get("card_type"):
                card_key = f"{payload.get('card_type')}:{payload.get('comp_name') or payload.get('title') or c['chunk_id']}"
                if card_key not in seen_card_keys:
                    seen_card_keys.add(card_key)
                    ui_cards.append(payload)

        return {
            "chunks": top_results,
            "ui_cards": ui_cards[:3],  # limit to top 3 cards to keep chat clean
            "cited_chunk_ids": [c["chunk_id"] for c in top_results],
        }
