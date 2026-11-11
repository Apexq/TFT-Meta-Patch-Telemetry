from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "riot_game_name", "riot_tag_line", "riot_region", "tier_badge", "plan_tier", "daily_quota_used", "daily_quota_limit")
    list_filter = ("plan_tier", "riot_region", "preferred_lang")
    search_fields = ("user__username", "user__email", "riot_game_name", "riot_tag_line", "riot_puuid")
