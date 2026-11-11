from django.contrib import admin
from .models import ChatSession, ChatMessage, RateLimitLog


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "guest_session_key", "mode", "is_pinned", "updated_at", "id")
    list_filter = ("mode", "is_pinned", "is_archived")
    search_fields = ("title", "guest_session_key", "user__username")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "model_used", "latency_ms", "feedback", "created_at")
    list_filter = ("role", "model_used", "feedback")
    search_fields = ("content_markdown", "session__title")


@admin.register(RateLimitLog)
class RateLimitLogAdmin(admin.ModelAdmin):
    list_display = ("identifier", "window_key", "request_count", "updated_at")
    search_fields = ("identifier", "window_key")
