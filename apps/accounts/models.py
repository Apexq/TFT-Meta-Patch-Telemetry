from django.db import models
from django.conf import settings
from django.utils import timezone


class UserProfile(models.Model):
    PLAN_CHOICES = [
        ("FREE", "Ücretsiz Plan (30 soru/gün)"),
        ("PRO", "Pro Koçluk Planı (500 soru/gün)"),
        ("ADMIN", "Sınırsız Yönetici"),
    ]
    LANG_CHOICES = [
        ("tr", "Türkçe"),
        ("en", "English"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Kullanıcı",
    )
    riot_puuid = models.CharField(
        max_length=128,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Riot PUUID",
    )
    riot_game_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="Riot Oyuncu Adı",
    )
    riot_tag_line = models.CharField(
        max_length=16,
        blank=True,
        default="",
        verbose_name="Riot Etiket (#)",
    )
    riot_region = models.CharField(
        max_length=16,
        default="TR1",
        verbose_name="Riot Bölgesi (TR1, EUW1 vb.)",
    )
    tier_badge = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="Derece Rozeti (Örn: MASTER I • 245 LP)",
    )
    plan_tier = models.CharField(
        max_length=16,
        choices=PLAN_CHOICES,
        default="FREE",
        verbose_name="Üyelik Planı",
    )
    daily_quota_limit = models.PositiveIntegerField(
        default=30,
        verbose_name="Günlük Soru Limiti",
    )
    daily_quota_used = models.PositiveIntegerField(
        default=0,
        verbose_name="Bugün Kullanılan Kota",
    )
    quota_reset_date = models.DateField(
        default=timezone.localdate,
        verbose_name="Son Kota Sıfırlama Tarihi",
    )
    preferred_lang = models.CharField(
        max_length=5,
        choices=LANG_CHOICES,
        default="tr",
        verbose_name="Tercih Edilen Dil",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Son Güncelleme")

    class Meta:
        verbose_name = "Kullanıcı Profili"
        verbose_name_plural = "Kullanıcı Profilleri"

    def __str__(self) -> str:
        riot_id = f" ({self.riot_game_name}#{self.riot_tag_line})" if self.riot_game_name else ""
        return f"{self.user.username}{riot_id} [{self.plan_tier}]"

    def check_and_reset_quota(self) -> None:
        """Gün değiştiğinde günlük kullanım sayacını sıfırlar."""
        today = timezone.localdate()
        if self.quota_reset_date < today:
            self.daily_quota_used = 0
            self.quota_reset_date = today
            self.save(update_fields=["daily_quota_used", "quota_reset_date"])

    def can_ask_question(self) -> bool:
        """Kullanıcının kalan soru hakkı olup olmadığını kontrol eder."""
        self.check_and_reset_quota()
        if self.plan_tier == "ADMIN":
            return True
        return self.daily_quota_used < self.daily_quota_limit

    def consume_quota(self) -> bool:
        """1 adet soru kotası harcar."""
        if not self.can_ask_question():
            return False
        self.daily_quota_used += 1
        self.save(update_fields=["daily_quota_used"])
        return True
