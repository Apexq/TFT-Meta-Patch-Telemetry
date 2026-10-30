"""
CommunityDragon (CDragon) & DataDragon Client strictly targeting TFT Set 18 (TFTSet18).
Handles:
- Live patch detection across Riot DataDragon (`versions.json`), CDragon `/latest/`, and CDragon `/pbe/`
- Automatic HTTP retry with backoff & DataDragon CDN fallback so transient network blips never fail CI
- Gzip-accelerated downloads & smart caching
- Extraction of Set 18 Playable Champions, Traits, and Items (with bilingual TR/EN names & PNG icons)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src import TARGET_MUTATOR, TARGET_SET_NUMBER

CDRAGON_BASE_URL = "https://raw.communitydragon.org"
DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


class CDragonClient:
    """Fetches and extracts TFT Set 18 Champions, Traits, and Items from CommunityDragon."""

    def __init__(self, lang: str = "tr_tr", use_cache: bool = True) -> None:
        self.lang = lang
        self.use_cache = use_cache
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _http_get_json(self, url: str, timeout: int = 35, retries: int = 3) -> Any:
        headers = {
            "User-Agent": "TFT-Set18-Meta-Analyzer/2.2 (https://github.com/Apexq/tft-meta-analyzer)",
            "Accept-Encoding": "gzip",
            "Cache-Control": "no-cache",
        }
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if resp.info().get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw.decode("utf-8"))
            except Exception as exc:
                last_err = exc
                if attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_err}")

    def get_ddragon_versions_list(self) -> List[str]:
        """Queries Riot's official DataDragon CDN for the ordered list of client versions."""
        try:
            versions = self._http_get_json(DDRAGON_VERSIONS_URL, timeout=15, retries=2)
            if isinstance(versions, list):
                return [str(v) for v in versions]
        except Exception:
            pass
        return []

    def get_ddragon_latest_version(self) -> str:
        versions = self.get_ddragon_versions_list()
        return versions[0] if versions else ""

    def get_available_cdragon_patches(self) -> List[str]:
        """
        Returns sorted numeric patch directories (e.g. ['16.20', '16.21']).
        Uses Riot DataDragon CDN first for instant speed, falling back to CDragon `/json/`.
        """
        dd_versions = self.get_ddragon_versions_list()
        seen_short: List[str] = []
        for v in dd_versions:
            parts = v.split(".")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                short_v = f"{parts[0]}.{parts[1]}"
                if short_v not in seen_short:
                    seen_short.append(short_v)
            if len(seen_short) >= 6:
                break

        if len(seen_short) >= 2:
            # Reverse so oldest -> newest (e.g. ['16.16', ..., '16.20', '16.21'])
            return list(reversed(seen_short))

        data = self._http_get_json(f"{CDRAGON_BASE_URL}/json/", timeout=25)
        versions: List[Tuple[int, int, str]] = []
        for entry in data:
            if entry.get("type") != "directory":
                continue
            name = entry.get("name", "")
            parts = name.split(".")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                versions.append((int(parts[0]), int(parts[1]), name))
        versions.sort()
        return [v[2] for v in versions]

    @staticmethod
    def compute_set18_fingerprint(set18_data: Dict[str, Any]) -> str:
        """Computes a deterministic SHA-256 fingerprint of Set 18 champions and traits."""
        payload = json.dumps(
            {
                "champions": set18_data.get("champions", []),
                "traits": set18_data.get("traits", []),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def resolve_patch_lifecycle_versions(self) -> Dict[str, str]:
        """
        Determines the active patch lifecycle versions on DataDragon & CDragon
        and maps them to TFT Set 18 patch labels (e.g. 18.4 -> 18.5 -> 18.6 PBE).
        """
        patches = self.get_available_cdragon_patches()
        if len(patches) < 2:
            raise RuntimeError("Insufficient patch history.")

        ddragon_ver = self.get_ddragon_latest_version()
        prev_cdragon = patches[-2]
        curr_cdragon = patches[-1]

        minor_num = int(curr_cdragon.split(".")[1])
        prev_minor_num = int(prev_cdragon.split(".")[1])

        set18_curr_patch = max(1, minor_num - 16)
        set18_prev_patch = max(1, prev_minor_num - 16)
        set18_pbe_patch = set18_curr_patch + 1

        return {
            "ddragon_version": ddragon_ver or curr_cdragon,
            "previous_cdragon": prev_cdragon,
            "latest_cdragon": curr_cdragon,
            "pbe_cdragon": "pbe",
            "previous_label": f"18.{set18_prev_patch}",
            "latest_label": f"18.{set18_curr_patch}",
            "pbe_label": f"18.{set18_pbe_patch} (PBE)",
        }

    def fetch_set18_data(self, cdragon_version: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Downloads CDragon TFT JSON for `cdragon_version` and extracts:
        - Playable Set 18 (`TFTSet18`) champions
        - Set 18 traits
        - Equippable TFT items (with names and icon paths for Best-in-Slot display)
        """
        cache_file = CACHE_DIR / f"set18_{cdragon_version}_{self.lang}.json"
        if self.use_cache and not force_refresh and cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if "items" in cached:
                return cached

        try:
            url = f"{CDRAGON_BASE_URL}/{cdragon_version}/cdragon/tft/{self.lang}.json"
            full_data = self._http_get_json(url, timeout=40)
        except Exception:
            if cdragon_version != "latest":
                url = f"{CDRAGON_BASE_URL}/latest/cdragon/tft/{self.lang}.json"
                full_data = self._http_get_json(url, timeout=40)
            else:
                raise

        set18_entry: Optional[Dict[str, Any]] = None
        for s in full_data.get("setData", []):
            if s.get("mutator") == TARGET_MUTATOR:
                set18_entry = s
                break

        if not set18_entry:
            set18_entry = full_data.get("sets", {}).get(str(TARGET_SET_NUMBER))

        if not set18_entry:
            raise ValueError(f"{TARGET_MUTATOR} (Set 18) not found in CDragon version '{cdragon_version}'.")

        playable_champions = []
        for champ in set18_entry.get("champions", []):
            traits = champ.get("traits") or []
            cost = champ.get("cost", 0)
            if traits and 1 <= cost <= 6:
                playable_champions.append(champ)

        items_dict: Dict[str, Dict[str, Any]] = {}
        for item in full_data.get("items", []):
            api_name = item.get("apiName")
            name = item.get("name")
            icon = item.get("icon")
            if api_name and name and icon:
                items_dict[api_name] = {
                    "apiName": api_name,
                    "name": name,
                    "icon": icon,
                }

        extracted = {
            "cdragon_version": cdragon_version,
            "mutator": TARGET_MUTATOR,
            "set_number": TARGET_SET_NUMBER,
            "set_name": set18_entry.get("name", "Set 18"),
            "champions": playable_champions,
            "traits": set18_entry.get("traits", []),
            "items": items_dict,
        }

        if self.use_cache:
            cache_file.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")

        return extracted

    @staticmethod
    def resolve_icon_url(asset_path: Optional[str], cdragon_version: str = "latest") -> str:
        """Converts a CDragon internal `.tex` or `.dds` asset path into a public PNG URL."""
        if not asset_path:
            return ""
        clean = asset_path.lower().strip("/")
        for ext in (".tex", ".dds"):
            if clean.endswith(ext):
                clean = clean[: -len(ext)] + ".png"
        return f"{CDRAGON_BASE_URL}/{cdragon_version}/game/{clean}"
