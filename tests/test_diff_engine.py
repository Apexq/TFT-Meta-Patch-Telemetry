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
