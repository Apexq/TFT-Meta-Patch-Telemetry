"""
AI Coach LLM Service for TFT Set 18.
Integrates Google Gemini REST API (gemini-2.5-flash / gemini-3.5-flash) with
a deterministic rule-based telemetry fallback when API key is missing or offline.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


class AICoachLLMService:
    """
    LLM Client for TFT Set 18 Coaching.
    Supports Google Gemini API with smart RAG context injection and graceful degradation.
    """

    MODEL_NAME = "gemini-3.1-flash-lite"

    @classmethod
    def get_api_key(cls) -> Optional[str]:
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    @classmethod
    def generate_coach_response(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        ui_cards: List[Dict[str, Any]],
        preferred_lang: str = "tr",
        mode: str = "META_COACH",
    ) -> Dict[str, Any]:
        """
        Generates AI coaching response using Gemini if available, or deterministic fallback.
        """
        api_key = cls.get_api_key()

        # Build clean RAG context block
        context_snippets = []
        for ch in retrieved_chunks[:6]:
            context_snippets.append(f"• [{ch.get('chunk_type')}] {ch.get('title_tr')}: {ch.get('content_text')}")
        context_text = "\n".join(context_snippets)

        system_instruction = (
            "Sen elit bir TFT Set 18 Challenger Koçusun. "
            "Kullanıcıların sorularına profesyonel, doğrudan ve hedefe yönelik yanıt verirsin. "
            "ÇOK ÖNEMLİ KURAL: Kullanıcı kısa, net bir soru sorduysa (örneğin 'Yasuo var mı bu sette?', 'Guinsoo kime verilir?', 'Bu yama ne zaman geldi?'), "
            "asla lafı uzatma, gereksiz uzun paragraflar ve zorlama taktikler yazma. Doğrudan 1-2 net cümleyle cevap ver (Örn: 'Hayır, Yasuo TFT Set 18 şampiyon havuzunda yer almıyor. Benzer yakın dövüş taşıyıcısı olarak Master Yi veya Rengar tercih edebilirsin.'). "
            "Sadece kullanıcı özellikle 'nasıl oynanır', 'rehber ver', 'detaylı analiz et', 'geçiş planı çıkar' gibi kapsamlı strateji istediğinde detaylı maddeleme yap. "
            "Gereksiz dolgu metinlerinden ve uzun selamlardan kaçın, samimi ve net ol. "
            "Eklentiler için asla sayısal kazanma oranı/sıralama yazma (Riot politikası); S/A/B/C kademelerini kullan."
        )

        user_prompt = (
            f"TFT Set 18 Coaching Query: '{query}'\n\n"
            f"Verified Patch 18.6 Telemetry Context:\n{context_text}\n\n"
            "Provide your strategic recommendation based strictly on this telemetry."
        )

        if api_key:
            try:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{cls.MODEL_NAME}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "generationConfig": {
                        "temperature": 0.4,
                        "maxOutputTokens": 2048,
                    },
                }

                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text_part:
                            return {
                                "content": text_part.strip(),
                                "model_used": cls.MODEL_NAME,
                                "success": True,
                            }
            except Exception as e:
                # Fallback to local deterministic response on any network or quota error
                pass

        # Smart Deterministic Telemetry Fallback
        fallback_content = cls._build_rule_based_coach_response(query, retrieved_chunks, ui_cards, preferred_lang)
        return {
            "content": fallback_content,
            "model_used": "telemetry-rag-engine",
            "success": True,
        }

    @classmethod
    def _build_rule_based_coach_response(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        ui_cards: List[Dict[str, Any]],
        lang: str = "tr",
    ) -> str:
        """
        Builds a high-quality deterministic coaching response directly from Master+ telemetry.
        """
        comps = [c for c in ui_cards if c.get("card_type") == "composition"]
        augments = [c for c in ui_cards if c.get("card_type") == "augment"]
        encounters = [c for c in ui_cards if c.get("card_type") == "encounter"]

        if lang == "tr":
            lines = [f"**TFT Set 18 (Yama 18.6) Koçluk Analizi:**\n"]
            if comps:
                lines.append(f"Sorun için Master+ verilerinde en yüksek performansı gösteren kompozisyonlar şunlardır:")
                for c in comps[:2]:
                    lines.append(f"• **{c.get('comp_name')} ({c.get('tier')} Tier)** — Tempo: `{c.get('levelling')}`, Ort. Sıralama: `#{c.get('avg_placement')}`, İlk 4: `%{c.get('top4_rate')}`.")
                    if c.get("carry_builds"):
                        carries = ", ".join(f"{cb.get('unit_name')} ({len(cb.get('items', []))} BiS)" for cb in c.get("carry_builds"))
                        lines.append(f"  *Taşıyıcılar:* {carries}")
                lines.append("\n*Aşağıdaki kompozisyon kartından 4x7 tahta dizilimini açabilir ve tek tıkla oyun içi Team Planner kodunu kopyalayabilirsin.*")

            elif augments:
                lines.append(f"Eklenti seçimleri için önerilen S-Tier eklentiler:")
                for a in augments[:3]:
                    lines.append(f"• **{a.get('name')} ({a.get('tier')} Tier, {a.get('rarity')})** — Aşama: {', '.join(a.get('rounds', []))}. Açıklama: {a.get('desc')}")

            elif encounters:
                lines.append(f"Set 18 Karşılaşma (Portal) taktik rehberi:")
                for enc in encounters[:2]:
                    lines.append(f"• **{enc.get('name')} ({enc.get('tempo_rating')})**: {enc.get('strategy_tr')}")

            else:
                lines.append(f"'{query}' sorusuna ilişkin mevcut Yama 18.6 telemetrisi:")
                for ch in retrieved_chunks[:3]:
                    lines.append(f"• {ch.get('title_tr')}: {ch.get('content_text')}")

            return "\n".join(lines)
        else:
            lines = [f"**TFT Set 18 (Patch 18.6) Coaching Assessment:**\n"]
            if comps:
                lines.append("Top-performing Master+ compositions matching your query:")
                for c in comps[:2]:
                    lines.append(f"• **{c.get('comp_name_en') or c.get('comp_name')} ({c.get('tier')} Tier)** — Leveling: `{c.get('levelling')}`, Avg Place: `#{c.get('avg_placement')}`, Top 4: `{c.get('top4_rate')}%`.")
                lines.append("\n*Expand the interactive card below for the 4x7 board layout and 1-click Team Planner code.*")
            else:
                for ch in retrieved_chunks[:3]:
                    lines.append(f"• {ch.get('title_en') or ch.get('title_tr')}: {ch.get('content_text')}")
            return "\n".join(lines)
