from django.contrib import admin
from .models import UserProfile, PromoCode, PromoRedemption, SubscriptionEvent


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "riot_game_name", "riot_tag_line", "riot_region", "tier_badge", "plan_tier", "daily_quota_used", "daily_quota_limit")
    list_filter = ("plan_tier", "riot_region", "preferred_lang")
    search_fields = ("user__username", "user__email", "riot_game_name", "riot_tag_line", "riot_puuid")


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "target_tier", "uses_count", "max_uses", "is_active", "expires_at", "note")
    list_filter = ("target_tier", "is_active")
    search_fields = ("code", "note")


@admin.register(PromoRedemption)
class PromoRedemptionAdmin(admin.ModelAdmin):
    list_display = ("user", "promo_code", "redeemed_at")
    search_fields = ("user__username", "promo_code__code")


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "user", "plan_tier", "status", "external_event_id", "created_at")
    list_filter = ("provider", "plan_tier", "status")
    search_fields = ("user__username", "external_event_id")
