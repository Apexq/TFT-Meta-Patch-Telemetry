"""
AI Coach LLM Service for TFT Meta & PBE Coaching.
Integrates Google Gemini REST API (generateContent + streamGenerateContent SSE + Multimodal Vision)
with a deterministic rule-based telemetry fallback when API key is missing or offline.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("apps.chat")


class AICoachLLMService:
    """
    LLM Client for TFT AI Coaching.
    Supports Google Gemini API (JSON structured output, SSE token streaming, and Vision)
    with smart RAG context injection and graceful offline degradation.
    """

    MODEL_NAME = "gemini-3.1-flash-lite"

    @classmethod
    def get_api_key(cls) -> Optional[str]:
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    @classmethod
    def _build_prompt_bundle(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        ui_cards: List[Dict[str, Any]],
        preferred_lang: str = "tr",
        mode: str = "META_COACH",
        history: Optional[List[Dict[str, str]]] = None,
        attached_match: Optional[Any] = None,
        image_data: Optional[Dict[str, str]] = None,
        for_streaming: bool = False,
    ) -> Dict[str, Any]:
        context_snippets = []
        for ch in retrieved_chunks[:8]:
            context_snippets.append(f"• [{ch.get('chunk_type')}] {ch.get('title_tr')}: {ch.get('content_text')}")
        context_text = "\n".join(context_snippets)

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

        match_telemetry_text = ""
        if attached_match:
            diag = getattr(attached_match, "ai_diagnosis_cache", None) or {}
            lobby = getattr(attached_match, "lobby_contested_json", None) or {}
            contested_units = lobby.get("contested_units", [])
            contested_desc = ", ".join(
                f"{u.get('unit_name')} ({u.get('opponents_count')} rakipte, %{int(u.get('pool_depleted_pct', 0))} havuz tükendi)"
                for u in contested_units
            ) if contested_units else "Lobide yoğun çekişme tespit edilmedi."
            mistakes_desc = "; ".join(diag.get("critical_mistakes", [])) or "Kritik makro hata saptanmadı."
            recs_desc = "; ".join(diag.get("recommendations", [])) or "Genel tempo ve ekonomi disiplinine devam et."
            match_telemetry_text = (
                f"\n--- BAĞLI TFT MAÇ TELEMETRİSİ ({attached_match.match_id}) ---\n"
                f"• Maç ID: {attached_match.match_id} (Yanıtının başında '{attached_match.match_id}' maç kodunu ve '#{attached_match.placement}' derecesini mutlaka belirt)\n"
                f"• Sıralama: #{attached_match.placement} (Yanıtında '#{attached_match.placement}' derecesini mutlaka belirt)\n"
                f"• Seviye: {attached_match.level} | Elenme/Bitiş Turu: {attached_match.last_round} | Kalan Altın: {attached_match.gold_left}g\n"
                f"• Değerlendirme: {diag.get('summary_headline', f'#{attached_match.placement} Sıralama Analizi')}\n"
                f"• Lobi Rekabeti (Contested): {contested_desc}\n"
                f"• Tespit Edilen Kritik Hatalar: {mistakes_desc}\n"
                f"• Önerilen Pivot ve Koçluk Tavsiyeleri: {recs_desc}\n"
                f"----------------------------------------------------\n\n"
            )

        pbe_rule = ""
        if mode == "PBE_SCOUT":
            pbe_rule = (
                "\n7. PBE İzci Modu (Yeni Set / Set 19):\n"
                "   - Kullanıcı şu an PBE'deki yeni set (Set 19) şampiyonları, özellikleri ve erken sinerjileri hakkında soru soruyor. "
                "TELEMETRİ BAĞLAMI içindeki `[pbe]` verilerini öncelikli kullan, PBE verilerinin canlıya geçmeden önce değişebileceğini kısaca not et.\n"
            )

        vision_rule = ""
        if image_data:
            vision_rule = (
                "\n8. Ekran Görüntüsü (Vision / Board OCR) Koçluğu:\n"
                "   - Kullanıcı oyun içi ekran görüntüsü yükledi. Görüntüdeki tahtayı, mevcut eşya bileşenlerini, altın/seviye/aşama bilgisini "
                "ve varsa dükkânı analiz et. Hangi eşyaları hemen birleştirmesi (slam) gerektiğini, en iyi pivot yolunu ve 4×7 dizilim önerisini net maddelerle yaz.\n"
            )

        lang_rule = (
            "Yanıt dilin doğal ve akıcı Türkçe olsun."
            if preferred_lang == "tr"
            else "Respond in crisp, natural English."
        )

        card_rule = (
            ""
            if for_streaming
            else (
                "4. Hextech Arayüz Kartı Seçimi (selected_card_ids):\n"
                "   - Sana aşağıda aday Hextech kart ID'leri verilmiştir. Bu kartları ekranda gösterip göstermemeye SEN karar ver:\n"
                "   - Kullanıcı bir kompozisyon, tahta dizilimi, eşya/build, eklenti, PBE özeti veya karşılaşma/tılsım önerisi istiyorsa ilgili kart ID'sini `selected_card_ids` dizisine ekle (en fazla 2 kart).\n"
                "   - Eğer soru basit bir varlık/yokluk kontrolü veya genel sohbetse `selected_card_ids` dizisini BOŞ (`[]`) bırak!\n\n"
            )
        )

        system_instruction = (
            "Sen elit ve samimi bir TFT Challenger Koçusun. "
            "Kullanıcıya yapay ve mekanik kalıplarla değil, tıpkı Discord'da konuşan deneyimli bir koç gibi esnek, doğal ve öneri odaklı rehberlik yaparsın. "
            f"{lang_rule}\n\n"
            "ÖNEMLİ PRENSİPLER VE YOL GÖSTERİCİLER:\n"
            "1. Soruya Göre Yanıt Uzunluğu Ayarla (Lafı Uzatma):\n"
            "   - Basit/net sorulara 1-2 samimi ve net cümleyle doğrudan yanıtla.\n"
            "   - Rehber, pivot, tempo veya dizilim istendiğinde aşama bazlı (2-1, 3-2, 4-2), eşya öncelikli ve akıcı bir plan ver.\n\n"
            "2. Veri Gerçekliği & Halüsinasyon Yasağı:\n"
            "   - Yalnızca verilen TELEMETRİ BAĞLAMI'ndaki canlı Set 18 ve varsa PBE Set 19 verilerine sadık kal. Olmayan şampiyon veya eşya uydurma!\n\n"
            "3. Öneri & Alternatif Odaklı Ol:\n"
            "   - Oyuncuyu tek bir kompozisyona mahkûm etme; lobi ve eşya akışına göre esnek alternatifler sun.\n\n"
            f"{card_rule}"
            "5. Riot İstatistik Politikası:\n"
            "   - Eklenti (Augment) kazanma oranı (%) veya sayısal ortalama sıralama yazma; yalnızca S/A/B kademeleri ve sinerji uyumlarını tavsiye et.\n\n"
            "6. Bağlı TFT Maç Analizi (Post-Game Coaching):\n"
            "   - Eğer oturumda 'BAĞLI TFT MAÇ TELEMETRİSİ' verilmişse, yanıtında Maç ID'sini ve '#...' bitiriş derecesini mutlaka belirterek "
            "contested birimler, dead gold ve pivot hatalarını doğrudan teşhis et."
            f"{pbe_rule}{vision_rule}"
        )

        user_prompt = (
            f"Kullanıcı Sorusu: '{query}'\n\n"
            f"{match_telemetry_text}"
            f"Doğrulanmış TFT Telemetri Bağlamı:\n{context_text}\n\n"
            + ("" if for_streaming else f"Aday Hextech Arayüz Kartları:\n{candidate_cards_text}")
        )

        contents: List[Dict[str, Any]] = []
        if history:
            for turn in history[-6:]:
                role = "model" if turn.get("role") in ("assistant", "model") else "user"
                text = (turn.get("content") or "").strip()[:1500]
                if text:
                    contents.append({"role": role, "parts": [{"text": text}]})

        final_parts: List[Dict[str, Any]] = [{"text": user_prompt}]
        if image_data and image_data.get("base64_data") and image_data.get("mime_type"):
            final_parts.append({
                "inlineData": {
                    "mimeType": image_data["mime_type"],
                    "data": image_data["base64_data"],
                }
            })
        contents.append({"role": "user", "parts": final_parts})

        return {
            "system_instruction": system_instruction,
            "contents": contents,
            "cards_by_id": cards_by_id,
        }

    @classmethod
    def select_cards_for_stream(
        cls,
        query: str,
        reply_text: str,
        ui_cards: List[Dict[str, Any]],
        mode: str = "META_COACH",
    ) -> List[Dict[str, Any]]:
        """
        Selects up to 2 relevant Hextech UI cards after streaming text completes.
        Automatically upgrades a composition card into a standalone `positioning_board`
        card when the user explicitly asks for hex positioning/layout.
        """
        if not ui_cards:
            return []

        q_low = (query or "").lower()
        r_low = (reply_text or "").lower()

        if mode == "PBE_SCOUT" or any(k in q_low for k in ("pbe", "set 19", "set19", "yeni set", "19.1")):
            pbe_cards = [c for c in ui_cards if c.get("card_type") == "pbe_preview"]
            if pbe_cards:
                return pbe_cards[:1]

        asks_positioning = any(
            k in q_low
            for k in ("dizilim", "konum", "position", "hex", "tahta", "ön saf", "arka saf", "köşe", "mirror")
        )
        if asks_positioning:
            for c in ui_cards:
                if c.get("card_type") == "composition" and c.get("board_grid"):
                    pos_card = {
                        "card_type": "positioning_board",
                        "card_id": f"pos:{c.get('cluster_id') or c.get('card_id')}",
                        "comp_name": c.get("comp_name"),
                        "comp_name_en": c.get("comp_name_en") or c.get("comp_name"),
                        "tier": c.get("tier", "S"),
                        "levelling": c.get("levelling", ""),
                        "board_grid": c.get("board_grid", []),
                        "units": c.get("units", [])[:10],
                        "team_planner_code": c.get("team_planner_code", ""),
                    }
                    return [pos_card]

        # Skip cards for very short greetings/yes-no questions unless cards are directly referenced
        short_chat = len(q_low.split()) <= 3 and any(
            g in q_low for g in ("merhaba", "selam", "hello", "hi", "teşekkür", "sağol", "eyvallah")
        )
        if short_chat:
            return []

        # Prefer cards whose title/name appears in the streamed reply or query
        scored = []
        for idx, card in enumerate(ui_cards):
            title = str(card.get("comp_name") or card.get("name") or card.get("title") or "").lower()
            title_en = str(card.get("comp_name_en") or card.get("name_en") or "").lower()
            hit = 0
            if title and (title in r_low or title in q_low):
                hit += 3
            if title_en and (title_en in r_low or title_en in q_low):
                hit += 2
            scored.append((hit, -idx, card))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in scored[:2]]

    @classmethod
    def generate_coach_response(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        ui_cards: List[Dict[str, Any]],
        preferred_lang: str = "tr",
        mode: str = "META_COACH",
        history: Optional[List[Dict[str, str]]] = None,
        attached_match: Optional[Any] = None,
        image_data: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Generates AI coaching response using Gemini if available, or deterministic fallback.
        Uses Structured JSON Output so the AI decides both the reply and which Hextech UI cards to display.
        """
        api_key = cls.get_api_key()
        bundle = cls._build_prompt_bundle(
            query=query,
            retrieved_chunks=retrieved_chunks,
            ui_cards=ui_cards,
            preferred_lang=preferred_lang,
            mode=mode,
            history=history,
            attached_match=attached_match,
            image_data=image_data,
            for_streaming=False,
        )
        cards_by_id = bundle["cards_by_id"]

        if api_key:
            try:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{cls.MODEL_NAME}:generateContent?key={api_key}"
                payload = {
                    "contents": bundle["contents"],
                    "systemInstruction": {"parts": [{"text": bundle["system_instruction"]}]},
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
                with urllib.request.urlopen(req, timeout=25) as resp:
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
                                return {
                                    "content": raw_text,
                                    "ui_cards": ui_cards[:2],
                                    "model_used": cls.MODEL_NAME,
                                    "success": True,
                                }
            except Exception as e:
                logger.warning(f"Gemini API call failed, falling back to local engine: {e}")

        fallback_content = cls._build_rule_based_coach_response(
            query,
            retrieved_chunks,
            ui_cards,
            preferred_lang,
            attached_match=attached_match,
            has_image=bool(image_data),
        )
        chosen = cls.select_cards_for_stream(query, fallback_content, ui_cards, mode=mode)
        return {
            "content": fallback_content,
            "ui_cards": chosen or ui_cards[:2],
            "model_used": "telemetry-rag-engine",
            "success": True,
        }

    @classmethod
    def stream_coach_response(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        ui_cards: List[Dict[str, Any]],
        preferred_lang: str = "tr",
        mode: str = "META_COACH",
        history: Optional[List[Dict[str, str]]] = None,
        attached_match: Optional[Any] = None,
        image_data: Optional[Dict[str, str]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Streams AI coaching response token-by-token via Gemini `streamGenerateContent?alt=sse`,
        falling back smoothly to chunked local telemetry output when API key is unavailable.
        Yields dicts of shape:
          - {"type": "token", "delta": "..."}
          - {"type": "cards", "ui_cards": [...]}
          - {"type": "done", "content": "...", "ui_cards": [...], "model_used": "..."}
        """
        api_key = cls.get_api_key()
        bundle = cls._build_prompt_bundle(
            query=query,
            retrieved_chunks=retrieved_chunks,
            ui_cards=ui_cards,
            preferred_lang=preferred_lang,
            mode=mode,
            history=history,
            attached_match=attached_match,
            image_data=image_data,
            for_streaming=True,
        )

        collected_parts: List[str] = []
        model_used = cls.MODEL_NAME
        streamed_ok = False

        if api_key:
            try:
                endpoint = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{cls.MODEL_NAME}:streamGenerateContent?alt=sse&key={api_key}"
                )
                payload = {
                    "contents": bundle["contents"],
                    "systemInstruction": {"parts": [{"text": bundle["system_instruction"]}]},
                    "generationConfig": {
                        "temperature": 0.35,
                        "maxOutputTokens": 2048,
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            chunk_obj = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        for cand in chunk_obj.get("candidates", []):
                            for part in cand.get("content", {}).get("parts", []):
                                delta = part.get("text", "")
                                if delta:
                                    collected_parts.append(delta)
                                    yield {"type": "token", "delta": delta}
                if collected_parts:
                    streamed_ok = True
            except Exception as exc:
                logger.warning(f"Gemini SSE stream failed, falling back to local engine: {exc}")

        if not streamed_ok:
            model_used = "telemetry-rag-engine"
            fallback_content = cls._build_rule_based_coach_response(
                query,
                retrieved_chunks,
                ui_cards,
                preferred_lang,
                attached_match=attached_match,
                has_image=bool(image_data),
            )
            collected_parts = [fallback_content]
            # Emit realistic word-group chunks for smooth streaming UI & testability
            words = fallback_content.split(" ")
            step = 8
            for i in range(0, len(words), step):
                piece = " ".join(words[i : i + step])
                if i + step < len(words):
                    piece += " "
                yield {"type": "token", "delta": piece}

        full_text = "".join(collected_parts).strip()
        chosen_cards = cls.select_cards_for_stream(query, full_text, ui_cards, mode=mode)
        yield {"type": "cards", "ui_cards": chosen_cards}
        yield {
            "type": "done",
            "content": full_text,
            "ui_cards": chosen_cards,
            "model_used": model_used,
        }

    @classmethod
    def _build_rule_based_coach_response(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        ui_cards: List[Dict[str, Any]],
        lang: str = "tr",
        attached_match: Optional[Any] = None,
        has_image: bool = False,
    ) -> str:
        """
        Builds a high-quality deterministic coaching response directly from Master+ & PBE telemetry.
        """
        comps = [c for c in ui_cards if c.get("card_type") == "composition"]
        augments = [c for c in ui_cards if c.get("card_type") == "augment"]
        pbe_cards = [c for c in ui_cards if c.get("card_type") == "pbe_preview"]

        if attached_match:
            placement = attached_match.placement
            level = attached_match.level
            last_round = attached_match.last_round
            gold_left = attached_match.gold_left
            diag = getattr(attached_match, "ai_diagnosis_cache", None) or {}
            lobby = getattr(attached_match, "lobby_contested_json", None) or {}
            headline = diag.get("summary_headline", f"#{placement} Sıralama Analizi")
            contested_units = lobby.get("contested_units", [])
            mistakes = diag.get("critical_mistakes", [])
            recommendations = diag.get("recommendations", [])

            if lang == "tr":
                lines = [
                    f"**TFT Set 18 Maç Sonu Analizi ({attached_match.match_id}):**\n",
                    f"Maçını detaylı olarak inceledim. Bu karşılaşmayı **#{placement}** sırada tamamladın (Seviye {level}, Aşama {last_round}, Kalan Altın: {gold_left}g).",
                    f"\n**Özet Teşhis:** {headline}",
                ]
                if contested_units:
                    contested_names = ", ".join(
                        f"{u.get('unit_name')} ({u.get('opponents_count')} rakipte, %{int(u.get('pool_depleted_pct', 0))} havuz tükendi)"
                        for u in contested_units
                    )
                    lines.append(f"\n**Lobi Rekabeti (Contested):** Tahtandaki kilit birimler lobide yoğun rekabet altındaydı: {contested_names}.")
                if gold_left >= 15 and placement > 4:
                    lines.append(f"\n**Ekonomi Riski (Dead Gold):** Elendiğinde tahtanda harcanmamış **{gold_left} altın** kaldı. Canın kritik seviyeye indiğinde bu altını seviye veya tahta gücüne (roll down) dönüştürmelisin.")
                if mistakes:
                    lines.append("\n**Kritik Hatalar:**")
                    for m in mistakes:
                        lines.append(f"• {m}")
                if recommendations:
                    lines.append("\n**Koç Tavsiyeleri & Pivot Planı:**")
                    for r in recommendations:
                        lines.append(f"• {r}")
                if comps:
                    lines.append("\n**Önerilen Alternatif Kompozisyonlar:**")
                    for c in comps[:2]:
                        lines.append(f"• **{c.get('comp_name')} ({c.get('tier')} Tier)** — Seviye temposu: `{c.get('levelling')}`.")
                return "\n".join(lines)
            else:
                lines = [
                    f"**TFT Set 18 Post-Game Match Review ({attached_match.match_id}):**\n",
                    f"I reviewed your match telemetry. You finished in **#{placement}** place (Level {level}, Stage {last_round}, Remaining Gold: {gold_left}g).",
                    f"\n**Assessment:** {headline}",
                ]
                if contested_units:
                    contested_names = ", ".join(
                        f"{u.get('unit_name')} (contested by {u.get('opponents_count')} players, {int(u.get('pool_depleted_pct', 0))}% pool depleted)"
                        for u in contested_units
                    )
                    lines.append(f"\n**Lobby Contention:** Key carries contested: {contested_names}.")
                if gold_left >= 15 and placement > 4:
                    lines.append(f"\n**Dead Gold Warning:** You exited with **{gold_left} unspent gold**. Roll down earlier when low on HP.")
                if mistakes:
                    lines.append("\n**Critical Mistakes:**")
                    for m in mistakes:
                        lines.append(f"• {m}")
                if recommendations:
                    lines.append("\n**Coach Recommendations:**")
                    for r in recommendations:
                        lines.append(f"• {r}")
                return "\n".join(lines)

        vision_prefix = ""
        if has_image:
            vision_prefix = (
                "*(Ekran görüntüsü eklendi — Gemini Vision API anahtarı aktif olduğunda tahta/dükkân doğrudan görsel olarak analiz edilir; şu an en yakın telemetri önerileri listeleniyor.)*\n\n"
                if lang == "tr"
                else "*(Screenshot attached — when Gemini Vision API key is active, board/shop visuals are analyzed directly; showing closest telemetry recommendations below.)*\n\n"
            )

        if pbe_cards:
            pbe = pbe_cards[0]
            five_names = ", ".join(c.get("name") or c.get("name_en") or "" for c in (pbe.get("champions_5g") or [])[:6])
            if lang == "tr":
                return (
                    f"{vision_prefix}**Set {pbe.get('set_number', 19)} PBE Erken Bakış ({pbe.get('pbe_label')}):**\n"
                    f"• Toplam **{pbe.get('total_champions', 0)} şampiyon** ve **{pbe.get('total_traits', 0)} özellik** tespit edildi.\n"
                    + (f"• Öne çıkan 5 altınlık şampiyonlar: **{five_names}**.\n" if five_names else "")
                    + "• PBE verileri canlı yamaya geçmeden önce denge değişikliklerine uğrayabilir."
                )
            return (
                f"{vision_prefix}**Set {pbe.get('set_number', 19)} PBE Early Preview ({pbe.get('pbe_label')}):**\n"
                f"• Tracking **{pbe.get('total_champions', 0)} champions** and **{pbe.get('total_traits', 0)} traits**.\n"
                + (f"• Highlighted 5-costs: **{five_names}**.\n" if five_names else "")
                + "• PBE values are subject to change before going live."
            )

        if lang == "tr":
            lines = [f"{vision_prefix}**TFT Meta Koçluk Notu:**\n"]
            if comps:
                lines.append("İlgilendiğin strateji için Master+ öne çıkan veriler:")
                for c in comps[:2]:
                    lines.append(f"• **{c.get('comp_name')} ({c.get('tier')} Tier)** — Seviye temposu: `{c.get('levelling')}`.")
                    if c.get("carry_builds"):
                        carries = ", ".join(f"{cb.get('unit_name')}" for cb in c.get("carry_builds"))
                        lines.append(f"  *Taşıyıcılar:* {carries}")
            elif augments:
                lines.append("Öne çıkan eklentiler:")
                for a in augments[:2]:
                    lines.append(f"• **{a.get('name')} ({a.get('tier')} Tier)**: {a.get('desc')}")
            else:
                for ch in retrieved_chunks[:2]:
                    lines.append(f"• {ch.get('title_tr')}: {ch.get('content_text')}")
            return "\n".join(lines)
        else:
            lines = [f"{vision_prefix}**TFT Meta Coaching Assessment:**\n"]
            if comps:
                lines.append("Top-performing Master+ compositions matching your query:")
                for c in comps[:2]:
                    lines.append(f"• **{c.get('comp_name_en') or c.get('comp_name')} ({c.get('tier')} Tier)** — Leveling: `{c.get('levelling')}`, Avg Place: `#{c.get('avg_placement')}`, Top 4: `{c.get('top4_rate')}%`.")
                lines.append("\n*Expand the interactive card below for the 4x7 board layout and 1-click Team Planner code.*")
            else:
                for ch in retrieved_chunks[:3]:
                    lines.append(f"• {ch.get('title_en') or ch.get('title_tr')}: {ch.get('content_text')}")
            return "\n".join(lines)
