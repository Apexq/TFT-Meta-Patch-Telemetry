from django.contrib import admin
from .models import PatchSnapshot, RAGChunk


@admin.register(PatchSnapshot)
class PatchSnapshotAdmin(admin.ModelAdmin):
    list_display = ("patch_label", "previous_label", "pbe_label", "is_active", "matches_analyzed", "fingerprint", "created_at")
    list_filter = ("is_active", "patch_label")
    search_fields = ("patch_label", "fingerprint")


@admin.register(RAGChunk)
class RAGChunkAdmin(admin.ModelAdmin):
    list_display = ("chunk_id", "chunk_type", "title_tr", "snapshot")
    list_filter = ("chunk_type", "snapshot__patch_label")
    search_fields = ("chunk_id", "title_tr", "title_en", "keywords_normalized")
