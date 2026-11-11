"""
Integration tests for Task 2: sync_tft_meta and TelemetryRAGService.
"""

import pytest
from django.core.management import call_command
from apps.telemetry.models import PatchSnapshot, RAGChunk
from apps.telemetry.services import TelemetryRAGService, normalize_query


@pytest.mark.django_db
def test_sync_tft_meta_populates_database_and_payloads():
    call_command("sync_tft_meta")

    snapshot = PatchSnapshot.objects.filter(is_active=True).first()
    assert snapshot is not None
    assert snapshot.patch_label == "18.6"
    assert snapshot.chunks.count() >= 400

    # Test Composition UI Card Payload
    comp_chunk = snapshot.chunks.filter(chunk_type="composition").first()
    assert comp_chunk is not None
    payload = comp_chunk.ui_card_payload
    assert payload.get("card_type") == "composition"
    assert "team_planner_code" in payload
    assert payload["team_planner_code"].endswith("TFTSet18")
    assert len(payload.get("units", [])) > 0

    # Test Augment UI Card Payload (Riot policy compliant)
    aug_chunk = snapshot.chunks.filter(chunk_type="augment").first()
    assert aug_chunk is not None
    aug_payload = aug_chunk.ui_card_payload
    assert aug_payload.get("card_type") == "augment"
    assert "tier" in aug_payload
    # Must not contain banned raw placement/winrate stats
    assert "avg_place" not in aug_payload
    assert "win_rate" not in aug_payload

    # Test Encounter & Charm UI Card Payloads
    enc_chunk = snapshot.chunks.filter(chunk_type="encounter").first()
    assert enc_chunk is not None
    assert enc_chunk.ui_card_payload.get("card_type") == "encounter"

    charm_chunk = snapshot.chunks.filter(chunk_type="charm").first()
    assert charm_chunk is not None
    assert charm_chunk.ui_card_payload.get("card_type") == "charm"


@pytest.mark.django_db
def test_telemetry_rag_service_retrieval_and_cards():
    call_command("sync_tft_meta")

    # Turkish normalization test
    assert normalize_query("Şampiyon İksiri Çantası") == "sampiyon iksiri cantasi"

    # Query 1: LeBlanc / Coven
    res = TelemetryRAGService.retrieve_chunks_and_cards("LeBlanc comp", top_k=6)
    assert len(res["chunks"]) > 0
    assert len(res["ui_cards"]) > 0
    assert any(c.get("card_type") == "composition" for c in res["ui_cards"])
    assert len(res["cited_chunk_ids"]) > 0

    # Query 2: Set 18 Encounter / Portal
    res_enc = TelemetryRAGService.retrieve_chunks_and_cards("altın şöleni portalı", top_k=4)
    assert any(c.get("card_type") == "encounter" for c in res_enc["ui_cards"])
