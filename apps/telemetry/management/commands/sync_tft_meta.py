"""
Management command to synchronize TFT Set 18 meta telemetry into Django database.
Reads from src/ pipeline artifacts (or executes full pipeline) and populates
PatchSnapshot and RAGChunk tables with Generative UI card payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.telemetry.models import PatchSnapshot, RAGChunk
from apps.telemetry.services import TelemetryRAGService


class Command(BaseCommand):
    help = "Syncs TFT Set 18 meta telemetry and RAG chunks into database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--report-path",
            type=str,
            default="docs/meta_report.json",
            help="Path to meta_report.json (default: docs/meta_report.json)",
        )
        parser.add_argument(
            "--rag-path",
            type=str,
            default="docs/api/rag_context.json",
            help="Path to rag_context.json (default: docs/api/rag_context.json)",
        )
        parser.add_argument(
            "--force-fetch",
            action="store_true",
            help="Execute src.main CLI to fetch latest CDragon/MetaTFT data before syncing",
        )

    def handle(self, *args, **options):
        base_dir = Path.cwd()
        report_file = base_dir / options["report_path"]
        rag_file = base_dir / options["rag_path"]

        if options["force_fetch"] or not report_file.exists():
            self.stdout.write(self.style.WARNING("Executing core Python data pipeline (src.main)..."))
            from src.main import run_pipeline
            run_pipeline(force=True)

        if not report_file.exists() or not rag_file.exists():
            self.stderr.write(self.style.ERROR(f"Pipeline output files missing: {report_file} or {rag_file}"))
            return

        self.stdout.write(f"Reading {report_file} and {rag_file}...")
        with open(report_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        with open(rag_file, "r", encoding="utf-8") as f:
            rag_payload = json.load(f)

        rag_chunks_raw = rag_payload.get("chunks", []) if isinstance(rag_payload, dict) else rag_payload

        versions = report_data.get("versions", {})
        patch_label = versions.get("latest_label", "18.6")
        previous_label = versions.get("previous_label", "18.5")
        pbe_label = versions.get("pbe_label", "18.7")
        cdragon_version = report_data.get("cdragon_version", "16.22")
        fingerprint = report_data.get("fingerprint") or report_data.get("set18_fingerprint") or f"snap-{patch_label}"
        matches_analyzed = report_data.get("live_meta", {}).get("matches_analyzed", 0)

        # Build index maps for Generative UI card payload attachments
        comps_by_id = {c.get("cluster_id"): c for c in report_data.get("live_meta", {}).get("compositions", [])}
        augments_by_id = {a.get("apiName"): a for a in report_data.get("augments", {}).get("augments", [])}
        encounters_by_id = {e.get("apiName"): e for e in report_data.get("mechanics", {}).get("encounters", [])}
        charms_by_id = {c.get("apiName"): c for c in report_data.get("mechanics", {}).get("charms", [])}

        with transaction.atomic():
            # Deactivate previous active snapshots
            PatchSnapshot.objects.filter(is_active=True).update(is_active=False)

            snapshot, created = PatchSnapshot.objects.update_or_create(
                patch_label=patch_label,
                fingerprint=fingerprint,
                defaults={
                    "previous_label": previous_label,
                    "pbe_label": pbe_label,
                    "cdragon_version": cdragon_version,
                    "is_active": True,
                    "matches_analyzed": matches_analyzed,
                    "full_report_json": report_data,
                },
            )

            action_str = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action_str} PatchSnapshot for Patch {patch_label} ({fingerprint})"))

            # Delete existing chunks for this snapshot to ensure clean refresh
            snapshot.chunks.all().delete()

            chunk_objects = []
            for item in rag_chunks_raw:
                chunk_id = item.get("id", "")
                chunk_type = item.get("type", "overview")
                title = item.get("title", "")
                keywords = item.get("keywords", "")
                content_text = item.get("text", "")

                ui_card_payload = {}

                # 1. Composition UI Card Payload
                if chunk_type == "composition":
                    # chunk_id format: comp:<cluster_id>
                    raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                    comp = comps_by_id.get(raw_id)
                    if comp:
                        ui_card_payload = {
                            "card_type": "composition",
                            "cluster_id": comp.get("cluster_id"),
                            "comp_name": comp.get("comp_name"),
                            "comp_name_en": comp.get("comp_name_en") or comp.get("comp_name"),
                            "tier": comp.get("tier"),
                            "levelling": comp.get("levelling"),
                            "meta_status": comp.get("meta_status"),
                            "comp_delta_score": comp.get("comp_delta_score", 0.0),
                            "active_traits": comp.get("active_traits", []),
                            "active_traits_en": comp.get("active_traits_en", []),
                            "avg_placement": comp.get("master_stats", {}).get("avg_placement", 4.5),
                            "top4_rate": comp.get("master_stats", {}).get("top4_rate", 50.0),
                            "win_rate": comp.get("master_stats", {}).get("win_rate", 12.5),
                            "team_planner_code": comp.get("team_planner_code", ""),
                            "comp_item_ids": comp.get("comp_item_ids", []),
                            "units": comp.get("units", [])[:8],
                            "carry_builds": comp.get("carry_builds", []),
                            "board_grid": comp.get("board_grid", []),
                            "level_schedule": comp.get("level_schedule", []),
                        }

                # 2. Augment UI Card Payload (Riot Policy Compliant - No raw placement or winrate)
                elif chunk_type == "augment":
                    raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                    aug = augments_by_id.get(raw_id)
                    if aug:
                        ui_card_payload = {
                            "card_type": "augment",
                            "apiName": aug.get("apiName"),
                            "name": aug.get("name"),
                            "name_en": aug.get("name_en"),
                            "tier": aug.get("tier"),
                            "tier_color": aug.get("tier_color", "#f0c374"),
                            "rarity": aug.get("rarity"),
                            "rarity_tr": aug.get("rarity_tr"),
                            "rounds": aug.get("rounds", []),
                            "tags": aug.get("tags", []),
                            "desc": aug.get("desc"),
                            "desc_en": aug.get("desc_en"),
                            "icon": aug.get("icon"),
                            "synergy_comps": aug.get("synergy_comps", []),
                        }

                # 3. Encounter / Portal UI Card Payload
                elif chunk_type == "encounter":
                    raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                    enc = encounters_by_id.get(raw_id)
                    if enc:
                        ui_card_payload = {
                            "card_type": "encounter",
                            "apiName": enc.get("apiName"),
                            "name": enc.get("name"),
                            "name_en": enc.get("name_en"),
                            "category": enc.get("category"),
                            "category_en": enc.get("category_en"),
                            "tempo_rating": enc.get("tempo_rating"),
                            "tempo_rating_en": enc.get("tempo_rating_en"),
                            "tempo_color": enc.get("tempo_color", "#a855f7"),
                            "post_spawn": enc.get("post_spawn"),
                            "post_spawn_en": enc.get("post_spawn_en"),
                            "strategy_tr": enc.get("strategy_tr"),
                            "strategy_en": enc.get("strategy_en"),
                            "synergy_comps_tr": enc.get("synergy_comps_tr", []),
                            "synergy_comps_en": enc.get("synergy_comps_en", []),
                        }

                # 4. Charm UI Card Payload
                elif chunk_type == "charm":
                    raw_id = chunk_id.split(":", 1)[-1] if ":" in chunk_id else chunk_id
                    chm = charms_by_id.get(raw_id)
                    if chm:
                        ui_card_payload = {
                            "card_type": "charm",
                            "apiName": chm.get("apiName"),
                            "name": chm.get("name"),
                            "name_en": chm.get("name_en"),
                            "cost": chm.get("cost"),
                            "tier": chm.get("tier"),
                            "category": chm.get("category"),
                            "category_tr": chm.get("category_tr"),
                            "stages": chm.get("stages"),
                            "desc": chm.get("desc"),
                            "desc_en": chm.get("desc_en"),
                            "rec_tr": chm.get("rec_tr"),
                            "rec_en": chm.get("rec_en"),
                        }

                chunk_objects.append(
                    RAGChunk(
                        snapshot=snapshot,
                        chunk_id=chunk_id,
                        chunk_type=chunk_type,
                        title_tr=title,
                        title_en=title,
                        keywords_normalized=keywords,
                        content_text=content_text,
                        ui_card_payload=ui_card_payload,
                    )
                )

            RAGChunk.objects.bulk_create(chunk_objects, batch_size=200)
            TelemetryRAGService.invalidate_cache()

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully synced {len(chunk_objects)} RAG chunks (with Generative UI payloads) into database!"
            )
        )
