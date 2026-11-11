from django.db import models


class PlayerMatchCache(models.Model):
    """
    Riot resmi tft-match-v1 API'sinden çekilen maç verilerini önbelleğe alır.
    Tekil match_id ile saklanır ve lobi rekabet analizi (contested units) içerir.
    """
    match_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Riot Maç Kimliği (Örn: TR1_1592837412)",
    )
    puuid = models.CharField(
        max_length=128,
        db_index=True,
        verbose_name="Oyuncu PUUID",
    )
    riot_id_display = models.CharField(
        max_length=96,
        db_index=True,
        verbose_name="Riot ID (Ad#Etiket)",
    )
    region = models.CharField(
        max_length=16,
        default="TR1",
        verbose_name="Sunucu Bölgesi",
    )
    patch_version = models.CharField(
        max_length=32,
        verbose_name="Oynandığı Yama Sürümü",
    )
    placement = models.PositiveSmallIntegerField(
        verbose_name="Bitiriş Sıralaması (1-8)",
    )
    level = models.PositiveSmallIntegerField(
        default=8,
        verbose_name="Son Ulaştığı Seviye",
    )
    gold_left = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Kalan Altın",
    )
    last_round = models.CharField(
        max_length=16,
        default="",
        verbose_name="Elenme / Galibiyet Turu (Örn: 5-4)",
    )
    player_board_json = models.JSONField(
        default=list,
        verbose_name="Oyuncunun Tahtası (Birimler, Yıldızlar, Eşyalar)",
    )
    active_traits_json = models.JSONField(
        default=list,
        verbose_name="Aktif Sinerjiler",
    )
    augments_selected_json = models.JSONField(
        default=list,
        verbose_name="Seçilen 3 Eklenti (Sayısal oran içermez)",
    )
    lobby_contested_json = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Lobi Rekabet Özeti (Diğer 7 oyuncunun tahtaları)",
    )
    ai_diagnosis_cache = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="AI Koç Maç Sonu Karnesi (Hatalar, Alternatifler)",
    )
    game_datetime = models.DateTimeField(
        db_index=True,
        verbose_name="Maçın Oynandığı Tarih / Saat",
    )
    fetched_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Önbelleğe Alınma Tarihi",
    )

    class Meta:
        verbose_name = "Oyuncu Maç Önbelleği"
        verbose_name_plural = "Oyuncu Maç Önbellekleri"
        ordering = ["-game_datetime"]

    def __str__(self) -> str:
        return f"{self.riot_id_display} - #{self.placement} ({self.match_id})"
