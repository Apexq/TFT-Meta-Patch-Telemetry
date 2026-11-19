"""Unit tests for TFT Set 18 Diff Engine."""

from src.diff_engine import Set18DiffEngine


def test_champion_buff_and_nerf_detection():
    engine = Set18DiffEngine()
    old_data = {
        "cdragon_version": "16.20",
        "champions": [
            {
                "apiName": "TFT18_Ahri",
                "name": "Ahri",
                "cost": 4,
                "traits": ["Mistik", "Büyücü"],
                "stats": {"hp": 700, "mana": 60, "damage": 45},
                "ability": {"name": "Küre", "variables": [{"name": "Damage", "value": [0, 200, 300, 900]}]},
            },
            {
                "apiName": "TFT18_Garen",
                "name": "Garen",
                "cost": 3,
                "traits": ["Muhafız"],
                "stats": {"hp": 900, "mana": 80, "damage": 60},
                "ability": {"name": "Yargı", "variables": [{"name": "Shield", "value": [0, 400, 500, 700]}]},
            },
        ],
        "traits": [],
    }
    new_data = {
        "cdragon_version": "16.21",
        "champions": [
            {
                "apiName": "TFT18_Ahri",
                "name": "Ahri",
                "cost": 4,
                "traits": ["Mistik", "Büyücü"],
                "stats": {"hp": 700, "mana": 50, "damage": 45},  # Max mana reduced -> BUFF
                "ability": {"name": "Küre", "variables": [{"name": "Damage", "value": [0, 240, 360, 1080]}]},  # +20% BUFF
            },
            {
                "apiName": "TFT18_Garen",
                "name": "Garen",
                "cost": 3,
                "traits": ["Muhafız"],
                "stats": {"hp": 800, "mana": 90, "damage": 60},  # HP reduced, mana increased -> NERF
                "ability": {"name": "Yargı", "variables": [{"name": "Shield", "value": [0, 350, 420, 600]}]},
            },
        ],
        "traits": [],
    }

    report = engine.compare_patches(old_data, new_data, "18.4", "18.5")
    assert report["set_number"] == 18
    assert report["summary_counts"]["buffed_champions"] == 1
    assert report["summary_counts"]["nerfed_champions"] == 1

    champ_by_name = {c["name"]: c for c in report["champion_diffs"]}
    assert champ_by_name["Ahri"]["status"] == "BUFF"
    assert champ_by_name["Ahri"]["impact_score"] > 0
    assert champ_by_name["Garen"]["status"] == "NERF"
    assert champ_by_name["Garen"]["impact_score"] < 0


def test_pbe_new_set_detection_and_metatft_lookup_fallback(tmp_path, monkeypatch):
    from src.cdragon_client import CDragonClient

    client = CDragonClient(lang="tr_tr", use_cache=False)

    # Simulate CDragon PBE still on Set 18 while MetaTFT already exposes Set 19
    def fake_http_get(url: str, timeout: int = 35, retries: int = 3):
        if "communitydragon.org" in url:
            return {
                "setData": [
                    {
                        "mutator": "TFTSet18",
                        "name": "Set 18",
                        "champions": [
                            {"apiName": f"TFT18_U{i}", "name": f"U{i}", "cost": 1, "traits": ["Bastion"]}
                            for i in range(16)
                        ],
                        "traits": [{"apiName": "TFT18_Bastion", "name": "Bastion", "effects": []}],
                    }
                ],
                "items": [],
            }
        if "TFTSet19_latest_tr_tr.json" in url:
            units = [
                {
                    "apiName": f"DA_19_Unit{i}",
                    "name": f"Birim {i}",
                    "en_name": f"Unit {i}",
                    "cost": 5 if i == 0 else 2,
                    "traits": ["K/DA", "Deha"],
                    "ability": {"name": "Skill", "variables": []},
                }
                for i in range(16)
            ]
            return {
                "_metadata": {"set": "TFTSet19", "setName": "Set 19", "release": "rls-19.1.0.123.Set19.pbe"},
                "units": units,
                "traits": [
                    {"apiName": "DA_19_KDA", "name": "K/DA", "desc": "KDA desc", "icon": "T_TraitIcon_19_KDA", "effects": [{"minUnits": 3}]}
                ],
                "items": [],
                "encounters": [],
            }
        raise RuntimeError("unexpected url")

    monkeypatch.setattr(client, "_http_get_json", fake_http_get)
    pbe_data = client.fetch_set18_data("pbe", force_refresh=True)

    assert pbe_data["set_number"] == 19
    assert pbe_data["mutator"] == "TFTSet19"
    assert pbe_data["patch_label"] == "19.1 (PBE)"
    assert len(pbe_data["champions"]) == 16
    assert pbe_data["champions"][0]["icon"] == "https://cdn.metatft.com/file/metatft/champions/da_19_unit0.png"
    assert pbe_data["traits"][0]["icon"] == "https://cdn.metatft.com/file/metatft/traits/t_traiticon_19_kda.png"
    assert CDragonClient.resolve_icon_url("https://cdn.metatft.com/x.png", "pbe") == "https://cdn.metatft.com/x.png"


def test_cross_set_diff_and_pbe_preview_rendering():
    from src.dashboard_builder import DashboardBuilder

    engine = Set18DiffEngine(
        icon_version="pbe",
        en_champ_names={"DA_19_Ahri": "Ahri"},
        en_trait_names={"DA_19_KDA": "K/DA"},
    )
    old_set18 = {
        "cdragon_version": "16.23",
        "set_number": 18,
        "champions": [{"apiName": "TFT18_Ahri", "name": "Ahri", "cost": 4, "traits": ["Bastion"], "stats": {}, "ability": {}}],
        "traits": [{"apiName": "TFT18_Bastion", "name": "Bastion", "effects": []}],
    }
    new_set19 = {
        "cdragon_version": "pbe",
        "set_number": 19,
        "champions": [
            {"apiName": "DA_19_Ahri", "name": "Ahri", "cost": 5, "traits": ["K/DA"], "icon": "https://cdn.metatft.com/a.png", "stats": {}, "ability": {"name": "Charm"}}
        ],
        "traits": [{"apiName": "DA_19_KDA", "name": "K/DA", "icon": "https://cdn.metatft.com/t.png", "effects": [{"minUnits": 3}]}],
    }

    diff = engine.compare_patches(old_set18, new_set19, "18.7", "19.1 (PBE)")
    assert diff["set_number"] == 19
    assert diff["is_new_set"] is True
    assert diff["summary_counts"]["total_champions_changed"] == 1
    assert diff["summary_counts"]["total_traits_changed"] == 1
    assert diff["trait_diffs"][0]["status"] == "NEW"

    builder = DashboardBuilder()
    report = {
        "generated_at": "2026-11-19 20:00 UTC",
        "versions": {"previous_label": "18.6", "latest_label": "18.7", "pbe_label": "19.1 (PBE)"},
        "ai_summary": {
            "live_headline": "L",
            "live_analysis": "LA",
            "pbe_headline": "19.1 (PBE): Set 19 Live",
            "pbe_analysis": "Set 19 preview active",
        },
        "live_diff": {"summary_counts": {"buffed_champions": 0, "buffed_traits": 0, "nerfed_champions": 0, "nerfed_traits": 0}, "champion_diffs": [], "trait_diffs": []},
        "live_meta": {"matches_analyzed": 1000, "total_comps": 0, "rising_comps_count": 0, "compositions": [], "riot_official_api": {"connected": False}},
        "pbe_diff": diff,
        "pbe_meta": {"compositions": []},
        "pbe_preview": {
            "is_new_set": True,
            "set_number": 19,
            "source": "MetaTFT PBE",
            "total_champions": 1,
            "total_traits": 1,
            "five_cost_count": 1,
            "champions": [
                {"name": "Ahri", "name_en": "Ahri", "cost": 5, "traits": ["K/DA"], "traits_en": ["K/DA"], "ability_name": "Charm", "ability_name_en": "Charm", "icon": "https://cdn.metatft.com/a.png"}
            ],
            "traits": [
                {"name": "K/DA", "name_en": "K/DA", "desc": "Buff", "desc_en": "Buff", "breakpoints": [3], "icon": "https://cdn.metatft.com/t.png"}
            ],
        },
        "leaderboards": {"regions": [], "total_players_listed": 0},
        "tier_lists": {"unit_tiers": [], "item_tiers": [], "matcher_items": []},
        "augments": None,
        "mechanics": None,
        "chat": {"endpoint": ""},
    }
    html = builder.env.get_template("index.html.j2").render(report=report)
    assert "19.1 (PBE)" in html
    assert "pbe-champ-grid" in html
    assert "K/DA" in html
