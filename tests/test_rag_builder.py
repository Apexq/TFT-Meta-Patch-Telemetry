"""Unit tests for the AI Knowledge Base (RAG) generator."""

from src.rag_builder import RAGBuilder, _normalize


def _sample_report():
    return {
        "generated_at": "2026-11-08 10:00 UTC",
        "set_number": 18,
        "versions": {"latest_label": "18.6", "previous_label": "18.5", "pbe_label": "18.7 (PBE)", "ddragon_version": "16.22.1"},
        "ai_summary": {"live_headline_en": "Headline", "live_analysis_en": "Analysis", "pbe_headline_en": "PBE", "pbe_analysis_en": "PBE analysis"},
        "live_meta": {
            "matches_analyzed": 1000,
            "total_comps": 1,
            "compositions": [{
                "cluster_id": 7,
                "comp_name": "Adaptör Master Yi",
                "comp_name_en": "Adaptor Master Yi",
                "tier": "A",
                "levelling": "lvl 7",
                "unit_count": 7,
                "active_traits": ["Adaptör"],
                "active_traits_en": ["Adaptor"],
                "units": [{"name": "Master Yi", "name_en": "Master Yi", "cost": 4, "is_carry": True}],
                "carry_builds": [{"unit_name": "Master Yi", "unit_name_en": "Master Yi",
                                  "items": [{"name": "Guinsoo'nun Hiddeti", "name_en": "Guinsoo's Rageblade"}]}],
                "master_stats": {"avg_placement": 4.27, "top4_rate": 52.0, "win_rate": 12.0, "sample_size": 5000},
                "comp_delta_score": 0.0,
                "meta_status_en": "STABLE",
                "level_schedule": [],
                "early_units": [],
                "team_planner_code": "0241600000000000000000000000000TFTSet18",
            }],
        },
        "live_diff": {"old_patch": "18.5", "new_patch": "18.6", "summary_counts": {}, "champion_diffs": [], "trait_diffs": []},
        "pbe_diff": {"champion_diffs": [], "trait_diffs": []},
        "tier_lists": {"item_tiers": [], "unit_tiers": []},
        "leaderboards": {"regions": []},
    }


def test_normalize_handles_turkish_characters():
    assert _normalize("Guinsoo'nun Hiddeti ŞAMPİYON Işık") == "guinsoo'nun hiddeti sampiyon isik"


def test_chunks_contain_comp_with_team_code_and_keywords():
    chunks = RAGBuilder(_sample_report()).build_chunks()
    comp = next(c for c in chunks if c["type"] == "composition")
    assert comp["team_planner_code"].endswith("TFTSet18")
    assert "TFTSet18" in comp["text"]
    assert "guinsoo's rageblade" in comp["keywords"]
    assert any(c.get("always_include") for c in chunks)


def test_llms_full_txt_lists_sections():
    builder = RAGBuilder(_sample_report())
    text = builder.build_llms_full_txt(builder.build_chunks())
    assert "## Master+ Meta Compositions" in text
    assert "Adaptor Master Yi" in text
