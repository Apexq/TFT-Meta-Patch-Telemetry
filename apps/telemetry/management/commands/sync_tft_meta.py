"""
Management command to synchronize TFT meta telemetry into Django database.
Reads from src/ pipeline artifacts (or executes full pipeline) and populates
PatchSnapshot and RAGChunk tables with Generative UI card payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
from django.core.management.base import BaseCommand

from apps.telemetry.services import sync_telemetry_payload


class Command(BaseCommand):
    help = "Syncs TFT meta telemetry (Live + PBE) and RAG chunks into database."

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

        result = sync_telemetry_payload(report_data, rag_payload)
        action_str = "Created" if result["created"] else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action_str} PatchSnapshot for Patch {result['patch_label']} "
                f"(PBE: {result['pbe_label']}, {result['fingerprint']})"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully synced {result['chunks_synced']} RAG chunks (with Generative UI payloads) into database!"
            )
        )
