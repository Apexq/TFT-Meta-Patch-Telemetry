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
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Generates AI coaching response using Gemini if available, or deterministic fallback.
        Uses Structured JSON Output so the AI decides both the reply and which Hextech UI cards to display.
        """
        api_key = cls.get_api_key()

        # Build clean RAG context block (always include overview + top chunks)
        context_snippets = []
        for ch in retrieved_chunks[:8]:
            context_snippets.append(f"• [{ch.get('chunk_type')}] {ch.get('title_tr')}: {ch.get('content_text')}")
        context_text = "\n".join(context_snippets)

        # Build candidate Hextech UI cards catalog so the AI can decide if any card should be shown
        candidate_cards_lines = []
        cards_by_id: Dict[str, Dict[str, Any]] = {}
        for card in ui_cards:
            cid = str(card.get("card_id") or "")
            if not cid:
                continue
            cards_by_id[cid] = card
            label = card.get("comp_name") or card.get("name") or card.get("title") or cid
            ctype = card.get("card_type", "card")
            tier = f" ({card.get('tier')} Tier)" if card.get("tier") else ""
            candidate_cards_lines.append(f"- ID: `{cid}` | Tür: {ctype} | Başlık: {label}{tier}")
        candidate_cards_text = "\n".join(candidate_cards_lines) if candidate_cards_lines else "(Aday kart yok)"

        system_instruction = (
            "Sen elit ve samimi bir TFT Set 18 Challenger Koçusun. "
            "Kullanıcıya yapay ve mekanik kalıplarla değil, tıpkı Discord'da konuşan deneyimli bir koç gibi esnek, doğal ve öneri odaklı rehberlik yaparsın.\n\n"
            "ÖNEMLİ PRENSİPLER VE YOL GÖSTERİCİLER:\n"
            "1. Soruya Göre Yanıt Uzunluğu Ayarla (Lafı Uzatma):\n"
            "   - Kullanıcı 'Yasuo var mı?', 'Guinsoo kime verilir?' veya selamlaşma gibi basit/net bir soru sorduysa, 1-2 samimi ve net cümleyle doğrudan yanıtla. İstenmeyen uzun analizler veya kompozisyon destanları yazma.\n"
            "   - Kullanıcı 'nasıl oynanmalı', 'erken aşamada ne yapmalıyım', 'rehber ver' dediğinde ise seviye temposu (örneğin 7'de slow roll mu yoksa Fast 8 mi), erken tahta tutuşu ve kritik eşya önceliklerini akıcı bir şekilde anlat.\n\n"
            "2. Set 18 Gerçekliği & Halüsinasyon Yasağı:\n"
            "   - Yalnızca verilen TELEMETRİ BAĞLAMI'ndaki Set 18 (Yama 18.6) verilerine sadık kal. Eğer sorulan şampiyon (örneğin Yasuo, Yone, Zed vb.) bu sette yoksa, doğrudan 'Bu şampiyon TFT Set 18'de bulunmuyor' de. Eski setlerden (Ionia, Shadow vb.) asla hayali kompozisyon veya eşya uydurma!\n\n"
            "3. Oyuncuyu Bir Şeye Mecbur Bırakma (Öneri & Alternatif Odaklı Ol):\n"
            "   - Kullanıcıyı tek bir kompozisyona ya da katı kurallara mahkûm etme ('bunu oynamak zorundasın' gibi konuşma). Oyunun durumuna göre esnek alternatifler öner.\n"
            "   - 'Aşağıdaki karta bak' veya 'Hextech kartını incele' gibi klişe yönlendirme cümlelerini sürekli tekrarlama.\n\n"
            "4. Hextech Arayüz Kartı Seçimi (selected_card_ids):\n"
            "   - Sana aşağıda aday Hextech kart ID'leri verilmiştir. Bu kartları ekranda gösterip göstermemeye SEN karar ver:\n"
            "   - Kullanıcı bir kompozisyon, tahta dizilimi, eşya/build, eklenti veya karşılaşma/tılsım önerisi istiyorsa ilgili kart ID'sini `selected_card_ids` dizisine ekle (en fazla 2 kart).\n"
            "   - Eğer soru basit bir varlık/yokluk kontrolü ('Yasuo var mı?'), genel sohbet/selamlaşma ya da zaten az önce gösterilmiş bir kart üzerine kısa devam sorusuysa (`compta neleri 2 lemeli?` gibi yeni karta ihtiyaç yoksa) `selected_card_ids` dizisini BOŞ (`[]`) bırak!\n\n"
            "5. Riot İstatistik Politikası:\n"
            "   - Eklenti (Augment) kazanma oranı (%) veya sayısal ortalama sıralama yazma; bunun yerine S/A/B kademeleri ve sinerji uyumlarını tavsiye et."
        )

        user_prompt = (
            f"Kullanıcı Sorusu: '{query}'\n\n"
            f"Doğrulanmış Set 18 Telemetri Bağlamı:\n{context_text}\n\n"
            f"Aday Hextech Arayüz Kartları:\n{candidate_cards_text}"
        )

        # Build multi-turn contents array (up to last 6 turns)
        contents: List[Dict[str, Any]] = []
        if history:
            for turn in history[-6:]:
                role = "model" if turn.get("role") in ("assistant", "model") else "user"
                text = (turn.get("content") or "").strip()[:1500]
                if text:
                    contents.append({"role": role, "parts": [{"text": text}]})
        contents.append({"role": "user", "parts": [{"text": user_prompt}]})

        if api_key:
            try:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{cls.MODEL_NAME}:generateContent?key={api_key}"
                payload = {
                    "contents": contents,
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 2048,
                        "thinkingConfig": {"thinkingBudget": 0},
                        "responseMimeType": "application/json",
                        "responseSchema": {
                            "type": "OBJECT",
                            "properties": {
                                "reply": {"type": "STRING"},
                                "selected_card_ids": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"},
                                },
                            },
                            "required": ["reply", "selected_card_ids"],
                        },
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
                        raw_text = "".join(
                            p.get("text", "")
                            for p in candidates[0].get("content", {}).get("parts", [])
                        ).strip()
                        if raw_text:
                            try:
                                parsed = json.loads(raw_text)
                                reply_text = str(parsed.get("reply") or "").strip()
                                selected_ids = parsed.get("selected_card_ids") or []
                                chosen_cards = [
                                    cards_by_id[str(cid)]
                                    for cid in selected_ids
                                    if str(cid) in cards_by_id
                                ][:2]
                                if reply_text:
                                    return {
                                        "content": reply_text,
                                        "ui_cards": chosen_cards,
                                        "model_used": cls.MODEL_NAME,
                                        "success": True,
                                    }
                            except json.JSONDecodeError:
                                # Fallback if model returned plain text despite responseSchema
                                return {
                                    "content": raw_text,
                                    "ui_cards": ui_cards[:2],
                                    "model_used": cls.MODEL_NAME,
                                    "success": True,
                                }
            except Exception as e:
                import logging
                logging.getLogger("apps.chat").warning(f"Gemini API call failed, falling back to local engine: {e}")
                pass

        # Smart Deterministic Telemetry Fallback
        fallback_content = cls._build_rule_based_coach_response(query, retrieved_chunks, ui_cards, preferred_lang)
        return {
            "content": fallback_content,
            "ui_cards": ui_cards[:2],
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
            lines = [f"**TFT Set 18 (Yama 18.6) Koçluk Notu:**\n"]
            if comps:
                lines.append(f"İlgilendiğin strateji için Master+ öne çıkan veriler:")
                for c in comps[:2]:
                    lines.append(f"• **{c.get('comp_name')} ({c.get('tier')} Tier)** — Seviye temposu: `{c.get('levelling')}`.")
                    if c.get("carry_builds"):
                        carries = ", ".join(f"{cb.get('unit_name')}" for cb in c.get("carry_builds"))
                        lines.append(f"  *Taşıyıcılar:* {carries}")
            elif augments:
                lines.append(f"Öne çıkan eklentiler:")
                for a in augments[:2]:
                    lines.append(f"• **{a.get('name')} ({a.get('tier')} Tier)**: {a.get('desc')}")
            else:
                for ch in retrieved_chunks[:2]:
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
