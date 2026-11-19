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
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src import TARGET_MUTATOR, TARGET_SET_NUMBER

CDRAGON_BASE_URL = "https://raw.communitydragon.org"
DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
METATFT_LOOKUP_URL = "https://data.metatft.com/lookups/TFTSet{set_num}_latest_{lang}.json"
METATFT_CHAMPION_CDN = "https://cdn.metatft.com/file/metatft/champions/{api_lower}.png"
METATFT_TRAIT_CDN = "https://cdn.metatft.com/file/metatft/traits/{icon_lower}.png"
STANDARD_SET_RE = re.compile(r"^TFTSet(\d+)$")
RELEASE_VER_RE = re.compile(r"rls-(\d+)\.(\d+)")
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
        except Exception as primary_err:
            try:
                if cdragon_version != "latest":
                    url = f"{CDRAGON_BASE_URL}/latest/cdragon/tft/{self.lang}.json"
                    full_data = self._http_get_json(url, timeout=40)
                else:
                    raise primary_err
            except Exception:
                # If CDragon is temporarily unreachable (e.g. HTTP 522), fall back to cached JSON if available
                if self.use_cache and cache_file.exists():
                    print(f"[CDragon Warning] Upstream unreachable ({primary_err}); using cached {cache_file.name}")
                    return json.loads(cache_file.read_text(encoding="utf-8"))
                fallback_caches = sorted(CACHE_DIR.glob(f"set18_*_{self.lang}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if self.use_cache and fallback_caches:
                    print(f"[CDragon Warning] Upstream unreachable ({primary_err}); using fallback cache {fallback_caches[0].name}")
                    return json.loads(fallback_caches[0].read_text(encoding="utf-8"))
                raise

        set_entry: Optional[Dict[str, Any]] = None
        detected_set_num = TARGET_SET_NUMBER
        detected_mutator = TARGET_MUTATOR

        if cdragon_version == "pbe":
            highest = self._find_standard_set_entry(full_data, prefer_highest=True)
            if highest:
                detected_set_num, detected_mutator, set_entry = highest

        if not set_entry:
            for s in full_data.get("setData", []):
                if s.get("mutator") == TARGET_MUTATOR:
                    set_entry = s
                    break

        if not set_entry:
            set_entry = full_data.get("sets", {}).get(str(TARGET_SET_NUMBER))

        if not set_entry:
            raise ValueError(f"{TARGET_MUTATOR} (Set {TARGET_SET_NUMBER}) not found in CDragon version '{cdragon_version}'.")

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

        if cdragon_version == "pbe" and detected_set_num <= TARGET_SET_NUMBER:
            next_set_data = self.fetch_metatft_set_lookup(
                TARGET_SET_NUMBER + 1,
                force_refresh=force_refresh,
                fallback_items=items_dict,
            )
            if next_set_data:
                if self.use_cache:
                    cache_file.write_text(json.dumps(next_set_data, ensure_ascii=False, indent=2), encoding="utf-8")
                return next_set_data

        playable_champions = [
            champ
            for champ in set_entry.get("champions", [])
            if (champ.get("traits") or []) and 1 <= champ.get("cost", 0) <= 6
        ]

        patch_label = f"{detected_set_num}.1 (PBE)" if (cdragon_version == "pbe" and detected_set_num != TARGET_SET_NUMBER) else ""
        extracted = {
            "cdragon_version": cdragon_version,
            "mutator": detected_mutator,
            "set_number": detected_set_num,
            "set_name": set_entry.get("name") if detected_set_num == TARGET_SET_NUMBER else f"Set {detected_set_num}",
            "patch_label": patch_label,
            "pbe_source": "CommunityDragon PBE" if cdragon_version == "pbe" else "CommunityDragon",
            "champions": playable_champions,
            "traits": set_entry.get("traits", []),
            "items": items_dict,
        }

        if self.use_cache:
            cache_file.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")

        return extracted

    @staticmethod
    def _find_standard_set_entry(
        full_data: Dict[str, Any],
        prefer_highest: bool = False,
    ) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        """Finds standard numeric TFT set entries (excluding special modes like PAIRS/TURBO)."""
        candidates: List[Tuple[int, str, Dict[str, Any]]] = []
        for s in full_data.get("setData", []):
            mutator = str(s.get("mutator") or "")
            m = STANDARD_SET_RE.match(mutator)
            if not m:
                continue
            playable_cnt = sum(
                1 for c in s.get("champions", [])
                if (c.get("traits") or []) and 1 <= c.get("cost", 0) <= 6
            )
            if playable_cnt >= 15:
                candidates.append((int(m.group(1)), mutator, s))

        for k, s in (full_data.get("sets") or {}).items():
            if not str(k).isdigit():
                continue
            set_num = int(k)
            if any(c[0] == set_num for c in candidates):
                continue
            playable_cnt = sum(
                1 for c in (s or {}).get("champions", [])
                if (c.get("traits") or []) and 1 <= c.get("cost", 0) <= 6
            )
            if playable_cnt >= 15:
                candidates.append((set_num, f"TFTSet{set_num}", s))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        if prefer_highest:
            return candidates[-1]
        for cand in candidates:
            if cand[0] == TARGET_SET_NUMBER:
                return cand
        return candidates[-1]

    def fetch_metatft_set_lookup(
        self,
        set_number: int,
        force_refresh: bool = False,
        fallback_items: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Queries MetaTFT's Set lookup JSON for upcoming PBE sets (e.g. Set 19) before
        CommunityDragon finishes syncing its `/pbe/` extract.
        """
        cache_file = CACHE_DIR / f"metatft_set{set_number}_{self.lang}.json"
        raw_lookup: Optional[Dict[str, Any]] = None

        if self.use_cache and not force_refresh and cache_file.exists():
            try:
                raw_lookup = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                raw_lookup = None

        if raw_lookup is None:
            url = METATFT_LOOKUP_URL.format(set_num=set_number, lang=self.lang)
            try:
                raw_lookup = self._http_get_json(url, timeout=15, retries=1)
                if self.use_cache and isinstance(raw_lookup, dict):
                    cache_file.write_text(json.dumps(raw_lookup, ensure_ascii=False), encoding="utf-8")
            except Exception:
                if self.use_cache and cache_file.exists():
                    try:
                        raw_lookup = json.loads(cache_file.read_text(encoding="utf-8"))
                    except Exception:
                        raw_lookup = None

        if not isinstance(raw_lookup, dict):
            return None

        playable_champions: List[Dict[str, Any]] = []
        for champ in raw_lookup.get("units", []):
            traits = champ.get("traits") or []
            cost = champ.get("cost", 0)
            api_name = champ.get("apiName")
            if api_name and traits and 1 <= cost <= 6:
                cdn_icon = METATFT_CHAMPION_CDN.format(api_lower=str(api_name).lower())
                champ_copy = dict(champ)
                champ_copy["icon"] = cdn_icon
                champ_copy["tileIcon"] = cdn_icon
                champ_copy["squareIcon"] = cdn_icon
                playable_champions.append(champ_copy)

        if len(playable_champions) < 15:
            return None

        traits_out: List[Dict[str, Any]] = []
        for tr in raw_lookup.get("traits", []):
            tr_copy = dict(tr)
            raw_icon = str(tr.get("icon") or "").strip()
            if raw_icon and not raw_icon.startswith(("http://", "https://")) and "/" not in raw_icon:
                tr_copy["icon"] = METATFT_TRAIT_CDN.format(icon_lower=raw_icon.lower())
            traits_out.append(tr_copy)

        items_dict: Dict[str, Dict[str, Any]] = dict(fallback_items or {})
        for item in raw_lookup.get("items", []):
            api_name = item.get("apiName")
            name = item.get("name")
            icon = item.get("icon")
            if api_name and name and icon:
                items_dict.setdefault(api_name, {"apiName": api_name, "name": name, "icon": icon})

        meta = raw_lookup.get("_metadata") or {}
        rel = str(meta.get("release") or "")
        rel_match = RELEASE_VER_RE.search(rel)
        patch_label = f"{rel_match.group(1)}.{rel_match.group(2)} (PBE)" if rel_match else f"{set_number}.1 (PBE)"

        return {
            "cdragon_version": "pbe",
            "mutator": str(meta.get("set") or f"TFTSet{set_number}"),
            "set_number": set_number,
            "set_name": str(meta.get("setName") or f"Set {set_number}"),
            "patch_label": patch_label,
            "pbe_source": "MetaTFT PBE",
            "champions": playable_champions,
            "traits": traits_out,
            "items": items_dict,
            "encounters": raw_lookup.get("encounters", []),
        }

    @staticmethod
    def resolve_icon_url(asset_path: Optional[str], cdragon_version: str = "latest") -> str:
        """Converts a CDragon internal `.tex` or `.dds` asset path into a public PNG URL."""
        if not asset_path:
            return ""
        raw = str(asset_path).strip()
        if raw.startswith(("http://", "https://")):
            return raw
        clean = raw.lower().strip("/")
        for ext in (".tex", ".dds"):
            if clean.endswith(ext):
                clean = clean[: -len(ext)] + ".png"
        return f"{CDRAGON_BASE_URL}/{cdragon_version}/game/{clean}"
