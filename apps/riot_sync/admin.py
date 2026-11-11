from django.contrib import admin
from .models import PlayerMatchCache


@admin.register(PlayerMatchCache)
class PlayerMatchCacheAdmin(admin.ModelAdmin):
    list_display = ("riot_id_display", "placement", "level", "patch_version", "region", "game_datetime", "match_id")
    list_filter = ("placement", "region", "patch_version")
    search_fields = ("riot_id_display", "puuid", "match_id")
