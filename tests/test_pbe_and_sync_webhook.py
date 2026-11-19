"""
Tests for Phase 1: Set 19 PBE Drawer, PBE_SCOUT RAG priority, and Telemetry Sync Webhook.
"""

import json
import pytest
from django.test import Client

from apps.telemetry.models import PatchSnapshot, RAGChunk
from apps.telemetry.services import TelemetryRAGService, sync_telemetry_payload


SAMPLE_REPORT_WITH_PBE = {
    "versions": {
        "previous_label": "18.7",
        "latest_label": "18.8",
        "pbe_label": "19.1 (PBE)",
    },
    "cdragon_version": "16.24",
    "fingerprint": "fp-live-188-pbe-191",
    "live_meta": {"matches_analyzed": 1500, "compositions": []},
    "augments": {"augments": []},
    "mechanics": {"encounters": [], "charms": []},
    "ai_summary": {
        "pbe_headline": "Set 19 PBE Yayında",
        "pbe_headline_en": "Set 19 PBE Live",
        "pbe_analysis": "94 şampiyon ve 50 özellik tespit edildi.",
        "pbe_analysis_en": "94 champions and 50 traits detected.",
    },
    "pbe_preview": {
        "set_number": 19,
        "source": "MetaTFT PBE",
        "total_champions": 2,
        "total_traits": 2,
        "champions": [
            {
                "apiName": "TFT19_AurelionSol",
                "name": "Aurelion Sol",
                "name_en": "Aurelion Sol",
                "cost": 5,
                "traits": ["Kozmik", "Büyücü"],
                "traits_en": ["Cosmic", "Sorcerer"],
                "icon": "https://cdn.metatft.com/file/metatft/champions/tft19_aurelionsol.png",
            },
            {
                "apiName": "TFT19_Zoe",
                "name": "Zoe",
                "name_en": "Zoe",
                "cost": 1,
                "traits": ["Kozmik"],
                "traits_en": ["Cosmic"],
                "icon": "https://cdn.metatft.com/file/metatft/champions/tft19_zoe.png",
            },
        ],
        "traits": [
            {
                "apiName": "TFT19_Cosmic",
                "name": "Kozmik",
                "name_en": "Cosmic",
                "breakpoints": [3, 5, 7],
                "desc": "Yıldız enerjisi toplar.",
                "desc_en": "Gathers star energy.",
                "icon": "",
            },
        ],
    },
    "pbe_meta": {"compositions": []},
}

SAMPLE_RAG_WITH_PBE = {
    "chunks": [
        {
            "id": "overview",
            "type": "overview",
            "title": "Patch 18.8 overview",
            "keywords": "meta patch 18.8 set 18",
            "text": "Live patch 18.8 overview text.",
        },
        {
            "id": "pbe",
            "type": "pbe",
            "title": "PBE preview 19.1 (PBE)",
            "keywords": "pbe set 19 tftset19 yeni set 19.1",
            "text": "Set 19 PBE includes Aurelion Sol and Cosmic trait.",
        },
        {
            "id": "pbe:champions_5g",
            "type": "pbe",
            "title": "Set 19 PBE 5-Cost Champions",
            "keywords": "pbe set 19 5 cost aurelion sol",
            "text": "5-Cost Aurelion Sol (Cosmic, Sorcerer).",
        },
    ]
}


@pytest.mark.django_db
class TestPbeAndSyncWebhook:
    def test_sync_webhook_rejects_unconfigured_or_invalid_token(self, monkeypatch):
        client = Client()

        monkeypatch.delenv("TELEMETRY_SYNC_TOKEN", raising=False)
        resp = client.post("/api/telemetry/sync/", data="{}", content_type="application/json")
        assert resp.status_code == 503

        monkeypatch.setenv("TELEMETRY_SYNC_TOKEN", "super-secret-sync-token")
        resp_bad = client.post(
            "/api/telemetry/sync/",
            data="{}",
            content_type="application/json",
            HTTP_X_SYNC_TOKEN="wrong-token",
        )
        assert resp_bad.status_code == 403

    def test_sync_webhook_updates_snapshot_pbe_cards_and_drawer(self, monkeypatch):
        monkeypatch.setenv("TELEMETRY_SYNC_TOKEN", "valid-sync-token-123")
        client = Client()

        resp = client.post(
            "/api/telemetry/sync/",
            data=json.dumps({
                "meta_report": SAMPLE_REPORT_WITH_PBE,
                "rag_context": SAMPLE_RAG_WITH_PBE,
            }),
            content_type="application/json",
            HTTP_X_SYNC_TOKEN="valid-sync-token-123",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "synced"
        assert body["pbe_label"] == "19.1 (PBE)"
        assert body["chunks_synced"] == 3

        snap = PatchSnapshot.objects.get(is_active=True)
        assert snap.pbe_label == "19.1 (PBE)"
        pbe_chunk = RAGChunk.objects.get(snapshot=snap, chunk_id="pbe")
        assert pbe_chunk.ui_card_payload["card_type"] == "pbe_preview"
        assert pbe_chunk.ui_card_payload["set_number"] == 19

        # Drawer renders Set 19 champions and traits
        drawer_resp = client.get("/drawers/pbe/")
        assert drawer_resp.status_code == 200
        html = drawer_resp.content.decode("utf-8")
        assert "Aurelion Sol" in html
        assert "Kozmik" in html
        assert "19.1 (PBE)" in html

    def test_pbe_scout_mode_prioritizes_pbe_chunks_and_card(self):
        sync_telemetry_payload(SAMPLE_REPORT_WITH_PBE, SAMPLE_RAG_WITH_PBE)
        res = TelemetryRAGService.retrieve_chunks_and_cards(
            query="Yeni sette 5 altınlık hangi şampiyonlar var?",
            mode="PBE_SCOUT",
        )
        chunk_types = [c["chunk_type"] for c in res["chunks"]]
        assert "pbe" in chunk_types
        card_types = [c["card_type"] for c in res["ui_cards"]]
        assert "pbe_preview" in card_types
