import uuid
from django.db import models


class PatchSnapshot(models.Model):
    """Her Set 18 yamasının kalıcı meta, diff ve telemetri durumunu saklar."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_label = models.CharField(max_length=32, db_index=True, verbose_name="Canlı Yama Etiketi (Örn: 18.6)")
    previous_label = models.CharField(max_length=32, verbose_name="Önceki Yama (Örn: 18.5)")
    pbe_label = models.CharField(max_length=32, default="", blank=True, verbose_name="PBE Etiketi (Örn: 18.7)")
    cdragon_version = models.CharField(max_length=32, default="", blank=True, verbose_name="CDragon Sürümü (Örn: 16.22)")
    fingerprint = models.CharField(max_length=64, db_index=True, verbose_name="SHA-256 Veri Özeti")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Aktif Canlı Yama mı?")
    matches_analyzed = models.PositiveIntegerField(default=0, verbose_name="İncelenen Master+ Maç Sayısı")
    full_report_json = models.JSONField(default=dict, blank=True, verbose_name="Tam meta_report.json İçeriği")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Kayıt Tarihi")

    class Meta:
        verbose_name = "Yama Anlık Görüntüsü (Snapshot)"
        verbose_name_plural = "Yama Anlık Görüntüleri"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        active_mark = " [AKTİF]" if self.is_active else ""
        return f"Patch {self.patch_label} ({self.fingerprint[:8]}){active_mark}"


class RAGChunk(models.Model):
    """
    Sohbet botunun retrieval araması yaptığı ve eşleştiğinde sohbet balonuna
    görsel kart (Generative UI Card) render ettiği zengin telemetri parçacığı.
    """
    CHUNK_TYPES = [
        ("overview", "Yama Genel Bakışı"),
        ("composition", "Meta Kompozisyon"),
        ("augment", "Eklenti (Augment)"),
        ("encounter", "Set 18 Karşılaşma (Portal)"),
        ("charm", "Dükkân Tılsımı (Charm)"),
        ("champion", "Şampiyon Tier & BiS"),
        ("item", "Eşya Tier"),
        ("patch_change", "Yama Denge Değişikliği (Buff/Nerf)"),
        ("leaderboard", "Bölgesel Challenger Sıralaması"),
        ("pbe", "PBE Erken Bakış"),
    ]

    snapshot = models.ForeignKey(
        PatchSnapshot,
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name="Bağlı Olduğu Yama",
    )
    chunk_id = models.CharField(
        max_length=128,
        db_index=True,
        verbose_name="Benzersiz Parçacık Kimliği (Örn: comp:426000)",
    )
    chunk_type = models.CharField(
        max_length=32,
        choices=CHUNK_TYPES,
        db_index=True,
        verbose_name="Parçacık Türü",
    )
    title_tr = models.CharField(max_length=255, verbose_name="Türkçe Başlık")
    title_en = models.CharField(max_length=255, default="", blank=True, verbose_name="İngilizce Başlık")
    keywords_normalized = models.TextField(
        verbose_name="Normalize Arama Anahtar Kelimeleri (TR + EN)",
    )
    content_text = models.TextField(
        verbose_name="LLM Sistem İstemine Gömülecek Temiz Metin",
    )
    ui_card_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Sohbet İçinde Görsel Kart Çizdirecek JSON Verisi",
    )

    class Meta:
        verbose_name = "RAG Bilgi Parçacığı"
        verbose_name_plural = "RAG Bilgi Parçacıkları"
        indexes = [
            models.Index(fields=["snapshot", "chunk_type"]),
            models.Index(fields=["chunk_id"]),
        ]

    def __str__(self) -> str:
        return f"[{self.chunk_type}] {self.title_tr} ({self.chunk_id})"
