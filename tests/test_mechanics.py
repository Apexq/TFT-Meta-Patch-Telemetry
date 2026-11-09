"""
Unit tests for Set 18 Augment Tier List and Special Mechanics Telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.cdragon_client import CDragonClient
from src.dashboard_builder import DashboardBuilder
from src.rag_builder import RAGBuilder
from src.riot_client import RiotTFTAnalyzer


@pytest.fixture
def mock_set18_data() -> dict:
    return {
        "cdragon_version": "16.22",
        "mutator": "TFTSet18",
        "set_number": 18,
        "set_name": "Set 18",
        "champions": [
            {"apiName": "TFT18_Yunara", "name": "Yunara", "cost": 4, "traits": ["TFT18_FloraFatalis"]},
            {"apiName": "TFT18_Leblanc", "name": "LeBlanc", "cost": 4, "traits": ["TFT18_Coven"]},
        ],
        "traits": [
            {"apiName": "TFT18_FloraFatalis", "name": "Ölümcül Flora"},
            {"apiName": "TFT18_Coven", "name": "Meclis"},
        ],
        "items": {},
    }


@pytest.fixture
def sample_meta_comps() -> list:
    return [
        {
            "cluster_id": "426000",
            "title": "4 Meclis LeBlanc",
            "title_en": "4 Coven LeBlanc",
            "comp_name": "4 Meclis LeBlanc",
            "comp_name_en": "4 Coven LeBlanc",
            "tier": "S",
            "avg_placement": 4.12,
            "comp_delta_score": 1.5,
            "meta_status": "YÜKSELEN",
            "meta_status_en": "RISING",
            "active_traits": ["Meclis 4"],
            "active_traits_en": ["Coven 4"],
            "buffed_units": ["LeBlanc"],
            "buffed_traits": [],
            "nerfed_units": [],
            "nerfed_traits": [],
            "levelling": "Fast 8",
            "unit_count": 8,
            "team_planner_code": "020000000000000000000000000000TFTSet18",
            "master_stats": {
                "avg_placement": 4.12,
                "top4_rate": 64.5,
                "win_rate": 18.2,
                "sample_size": 2500,
            },
            "units": [
                {"name": "LeBlanc", "name_en": "LeBlanc", "cost": 4, "is_carry": True, "icon": "", "is_three_star": False, "patch_status": "BUFF"}
            ],
            "carry_builds": [
                {"unit_name": "LeBlanc", "unit_name_en": "LeBlanc", "items": [{"name": "Rabadon", "name_en": "Rabadon's Deathcap"}]}
            ],
        },
        {
            "cluster_id": "426001",
            "title": "6 Karaçalı Sylas",
            "title_en": "6 Blackthorn Sylas",
            "comp_name": "6 Karaçalı Sylas",
            "comp_name_en": "6 Blackthorn Sylas",
            "tier": "A",
            "avg_placement": 4.28,
            "comp_delta_score": 0.0,
            "meta_status": "STABİL",
            "meta_status_en": "STABLE",
            "active_traits": ["Karaçalı 6"],
            "active_traits_en": ["Blackthorn 6"],
            "buffed_units": [],
            "buffed_traits": [],
            "nerfed_units": [],
            "nerfed_traits": [],
            "levelling": "Fast 8",
            "unit_count": 8,
            "team_planner_code": "020000000000000000000000000000TFTSet18",
            "master_stats": {
                "avg_placement": 4.28,
                "top4_rate": 56.0,
                "win_rate": 13.5,
                "sample_size": 1800,
            },
            "units": [
                {"name": "Sylas", "name_en": "Sylas", "cost": 4, "is_carry": True, "icon": "", "is_three_star": False, "patch_status": "UNCHANGED"}
            ],
            "carry_builds": [],
        },
    ]


def test_fetch_augment_tier_list(mock_set18_data, sample_meta_comps):
    analyzer = RiotTFTAnalyzer()
    aug_report = analyzer.fetch_augment_tier_list(
        set18_data=mock_set18_data,
        icon_version="latest",
        meta_compositions=sample_meta_comps,
    )

    assert "total_augments" in aug_report
    assert aug_report["total_augments"] > 100
    assert "tier_counts" in aug_report
    assert aug_report["tier_counts"]["S"] > 0
    assert aug_report["tier_counts"]["A"] > 0
    assert "rarity_counts" in aug_report
    assert aug_report["rarity_counts"]["Gold"] > 0
    assert aug_report["rarity_counts"]["Prismatic"] > 0

    augments = aug_report["augments"]
    assert len(augments) == aug_report["total_augments"]

    sample_aug = augments[0]
    assert "apiName" in sample_aug
    assert "name" in sample_aug
    assert "name_en" in sample_aug
    assert sample_aug["tier"] in ("S", "A", "B", "C", "D")
    assert 3.5 <= sample_aug["avg_place"] <= 5.5
    assert 0.0 <= sample_aug["pick_rate"] <= 100.0
    assert sample_aug["rarity"] in ("Silver", "Gold", "Prismatic")
    assert isinstance(sample_aug["rounds"], list)
    assert len(sample_aug["rounds"]) > 0
    assert sample_aug["icon"].startswith("http")
    # Verify description is cleaned of XML tags
    assert "<TFTCurveTable" not in sample_aug["desc"]
    assert "<TFTCurveTable" not in sample_aug["desc_en"]


def test_fetch_set18_mechanics_telemetry(mock_set18_data, sample_meta_comps):
    analyzer = RiotTFTAnalyzer()
    mech_report = analyzer.fetch_set18_mechanics_telemetry(
        set18_data=mock_set18_data,
        icon_version="latest",
        meta_compositions=sample_meta_comps,
    )

    assert "total_encounters" in mech_report
    assert mech_report["total_encounters"] == 20
    assert len(mech_report["encounters"]) == 20

    enc_apis = [e["apiName"] for e in mech_report["encounters"]]
    assert "DA_18_GoldenGala" in enc_apis
    assert "DA_18_PrismaticParty" in enc_apis
    assert "DA_18_CheaperLevels" in enc_apis

    sample_enc = mech_report["encounters"][0]
    assert "name" in sample_enc
    assert "name_en" in sample_enc
    assert "tempo_rating" in sample_enc
    assert "strategy_tr" in sample_enc
    assert "strategy_en" in sample_enc
    assert len(sample_enc["strategy_tr"]) > 20

    # Test Charms
    assert "charms" in mech_report
    charms = mech_report["charms"]
    assert len(charms) >= 20

    charm_cats = {c["category"] for c in charms}
    assert "Combat" in charm_cats
    assert "Econ" in charm_cats
    assert "Risky" in charm_cats
    assert "Item" in charm_cats
    assert "Scaling" in charm_cats

    for ch in charms:
        assert isinstance(ch["cost"], int)
        assert ch["tier"] in (1, 2, 3)
        assert len(ch["desc"]) > 0
        assert len(ch["rec_tr"]) > 0


def test_rag_builder_augments_and_mechanics(mock_set18_data, sample_meta_comps):
    analyzer = RiotTFTAnalyzer()
    aug_report = analyzer.fetch_augment_tier_list(mock_set18_data, meta_compositions=sample_meta_comps)
    mech_report = analyzer.fetch_set18_mechanics_telemetry(mock_set18_data, meta_compositions=sample_meta_comps)

    full_report = {
        "generated_at": "2026-11-09 13:00 UTC",
        "set_number": 18,
        "mutator": "TFTSet18",
        "versions": {"latest_label": "18.6", "previous_label": "18.5", "pbe_label": "18.7"},
        "ai_summary": {"live_headline": "Test", "live_analysis": "Test"},
        "live_diff": {"summary_counts": {"buffed_champions": 0, "buffed_traits": 0, "nerfed_champions": 0, "nerfed_traits": 0}},
        "live_meta": {"matches_analyzed": 1000, "total_comps": 2, "compositions": sample_meta_comps},
        "pbe_diff": {},
        "pbe_meta": {},
        "leaderboards": {},
        "tier_lists": {"unit_tiers": [], "item_tiers": []},
        "augments": aug_report,
        "mechanics": mech_report,
    }

    rag = RAGBuilder(full_report)
    chunks = rag.build_chunks()

    types = {c["type"] for c in chunks}
    assert "augment" in types
    assert "encounter" in types
    assert "charm" in types

    aug_chunks = [c for c in chunks if c["type"] == "augment"]
    enc_chunks = [c for c in chunks if c["type"] == "encounter"]
    charm_chunks = [c for c in chunks if c["type"] == "charm"]

    assert len(aug_chunks) > 100
    assert len(enc_chunks) == 20
    assert len(charm_chunks) >= 20

    full_txt = rag.build_llms_full_txt(chunks)
    assert "## Augment Tier List" in full_txt
    assert "## Set 18 Encounters & Portals" in full_txt
    assert "## Set 18 In-Shop Charms & Economy" in full_txt


def test_dashboard_renders_augments_and_mechanics(mock_set18_data, sample_meta_comps, tmp_path, monkeypatch):
    analyzer = RiotTFTAnalyzer()
    aug_report = analyzer.fetch_augment_tier_list(mock_set18_data, meta_compositions=sample_meta_comps)
    mech_report = analyzer.fetch_set18_mechanics_telemetry(mock_set18_data, meta_compositions=sample_meta_comps)

    full_report = {
        "generated_at": "2026-11-09 13:00 UTC",
        "set_number": 18,
        "mutator": "TFTSet18",
        "versions": {"latest_label": "18.6", "previous_label": "18.5", "pbe_label": "18.7"},
        "ai_summary": {"live_headline": "Test", "live_analysis": "Test", "engine": "CDragon", "engine_en": "CDragon"},
        "live_diff": {
            "summary_counts": {"buffed_champions": 0, "buffed_traits": 0, "nerfed_champions": 0, "nerfed_traits": 0},
            "champion_diffs": [],
            "trait_diffs": [],
        },
        "live_meta": {
            "matches_analyzed": 1000,
            "total_comps": 2,
            "rising_comps_count": 1,
            "compositions": sample_meta_comps,
            "riot_official_api": {"connected": False},
        },
        "pbe_diff": {"summary_counts": {"buffed_champions": 0, "buffed_traits": 0, "nerfed_champions": 0, "nerfed_traits": 0}},
        "pbe_meta": {"total_comps": 0, "compositions": []},
        "leaderboards": {"regions": [], "total_players_listed": 0},
        "tier_lists": {"unit_tiers": [], "item_tiers": [], "matcher_items": []},
        "augments": aug_report,
        "mechanics": mech_report,
        "chat": {"endpoint": "https://test.workers.dev"},
    }

    builder = DashboardBuilder()
    template = builder.env.get_template("index.html.j2")
    rendered_html = template.render(report=full_report)

    assert "panel-augments" in rendered_html
    assert "panel-mechanics" in rendered_html
    assert "btn-tab-augments" in rendered_html
    assert "btn-tab-mechanics" in rendered_html
    assert "subpanel-encounters" in rendered_html
    assert "subpanel-charms" in rendered_html
    assert "Golden Gala" in rendered_html
    assert "Altın Şöleni" in rendered_html
    assert "Aftershock" in rendered_html
    assert "Artçı Sarsıntı" in rendered_html
