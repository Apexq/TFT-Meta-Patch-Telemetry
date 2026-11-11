import uuid
from django.db import models
from django.conf import settings
from apps.telemetry.models import PatchSnapshot
from apps.riot_sync.models import PlayerMatchCache


class ChatSession(models.Model):
    """Sol menüde listelenen geçmiş sohbet oturumları."""
    MODE_CHOICES = [
        ("META_COACH", "Genel Meta Koçu"),
        ("OPENER_BUILDER", "Elimdekilerle Ne Oynarım?"),
        ("POST_GAME", "Maç Sonu Analizi"),
        ("PATCH_DIFF", "Yama Farkı & Denge Analizi"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        verbose_name="Kullanıcı (Üye)",
    )
    guest_session_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Misafir Oturum Anahtarı",
    )
    patch_snapshot = models.ForeignKey(
        PatchSnapshot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Konuşulan Yama",
    )
    attached_match = models.ForeignKey(
        PlayerMatchCache,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Bağlı TFT Maçı",
    )
    title = models.CharField(
        max_length=160,
        default="Yeni TFT Koçluk Sohbeti",
        verbose_name="Sohbet Başlığı",
    )
    mode = models.CharField(
        max_length=24,
        choices=MODE_CHOICES,
        default="META_COACH",
        verbose_name="Koçluk Modu",
    )
    selected_items_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Seçili Eşya Bileşenleri (Opener Modu)",
    )
    is_pinned = models.BooleanField(default=False, verbose_name="Başa Sabitlendi mi?")
    is_archived = models.BooleanField(default=False, verbose_name="Arşivlendi mi?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, db_index=True, verbose_name="Son Etkinlik")

    class Meta:
        verbose_name = "Sohbet Oturumu"
        verbose_name_plural = "Sohbet Oturumları"
        ordering = ["-is_pinned", "-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["guest_session_key", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.mode})"


class ChatMessage(models.Model):
    """
    Sohbet içindeki her bir soru ve zengin yanıt.
    ui_cards_json alanı sohbet balonunun altında basılacak 4x7 tahta ve
    kompozisyon kartlarının payload listesini barındırır.
    """
    ROLE_CHOICES = [
        ("user", "Kullanıcı"),
        ("assistant", "AI Koç"),
        ("system", "Sistem"),
    ]

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Bağlı Olduğu Sohbet",
    )
    role = models.CharField(
        max_length=16,
        choices=ROLE_CHOICES,
        verbose_name="Rol",
    )
    content_markdown = models.TextField(
        verbose_name="Mesaj Metni (Markdown)",
    )
    ui_cards_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Mesaj Altında Basılacak Görsel Kartlar (Generative UI)",
    )
    cited_chunk_ids = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Kullanılan RAG Bilgi Parçacıkları",
    )
    latency_ms = models.PositiveIntegerField(
        default=0,
        verbose_name="Yanıt Gecikmesi (Milisaniye)",
    )
    model_used = models.CharField(
        max_length=64,
        default="gemini-2.5-flash",
        verbose_name="Kullanılan Yapay Zekâ Modeli",
    )
    feedback = models.SmallIntegerField(
        default=0,
        choices=[(1, "Beğenildi"), (-1, "Hatalı Bulundu"), (0, "Oylanmadı")],
        verbose_name="Kullanıcı Beğeni Oyu",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Gönderilme Zamanı",
    )

    class Meta:
        verbose_name = "Sohbet Mesajı"
        verbose_name_plural = "Sohbet Mesajları"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.role.upper()}: {self.content_markdown[:40]}..."


class RateLimitLog(models.Model):
    """IP ve Kullanıcı bazlı hız/maliyet sınırlama tablosu."""
    identifier = models.CharField(
        max_length=128,
        db_index=True,
        verbose_name="İstemci Kimliği (IP Hash veya User ID)",
    )
    window_key = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name="Zaman Penceresi Anahtarı (Örn: min:202611111730)",
    )
    request_count = models.PositiveIntegerField(
        default=1,
        verbose_name="Yapılan İstek Sayısı",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hız Sınırı Günlüğü"
        verbose_name_plural = "Hız Sınırı Günlükleri"
        unique_together = [("identifier", "window_key")]

    def __str__(self) -> str:
        return f"{self.identifier} @ {self.window_key} ({self.request_count} req)"
