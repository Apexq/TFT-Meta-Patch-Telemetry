"""
Webhook & API views for apps.telemetry.
Allows GitHub Actions (or trusted automation) to trigger atomic PatchSnapshot + RAGChunk sync.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.telemetry.services import sync_telemetry_payload


@csrf_exempt
@require_POST
def telemetry_sync_webhook_view(request: HttpRequest) -> JsonResponse:
    """
    POST /api/telemetry/sync/
    Authenticates via constant-time `X-Sync-Token` header against `TELEMETRY_SYNC_TOKEN`.
    Accepts either:
      - JSON body with `meta_report` and `rag_context` payloads, OR
      - Empty body / `{"source": "local"}` to reload `docs/meta_report.json` & `docs/api/rag_context.json`.
    """
    expected_token = (os.getenv("TELEMETRY_SYNC_TOKEN") or "").strip()
    if not expected_token:
        return JsonResponse(
            {"error": "TELEMETRY_SYNC_TOKEN is not configured on this server."},
            status=503,
        )

    provided_token = (
        request.headers.get("X-Sync-Token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        return JsonResponse({"error": "Invalid or missing sync token."}, status=403)

    body = {}
    if request.body:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    report_data = body.get("meta_report") if isinstance(body, dict) else None
    rag_payload = body.get("rag_context") if isinstance(body, dict) else None

    if report_data is None or rag_payload is None:
        base_dir = Path(settings.BASE_DIR)
        report_file = base_dir / "docs" / "meta_report.json"
        rag_file = base_dir / "docs" / "api" / "rag_context.json"
        if not report_file.exists() or not rag_file.exists():
            return JsonResponse(
                {"error": "meta_report/rag_context payload omitted and local docs/ files not found."},
                status=400,
            )
        with open(report_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)
        with open(rag_file, "r", encoding="utf-8") as f:
            rag_payload = json.load(f)

    result = sync_telemetry_payload(report_data, rag_payload)
    return JsonResponse({
        "status": "synced",
        "created": result["created"],
        "patch_label": result["patch_label"],
        "pbe_label": result["pbe_label"],
        "fingerprint": result["fingerprint"],
        "chunks_synced": result["chunks_synced"],
    })
