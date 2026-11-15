from django.db import models
from django.conf import settings
from django.utils import timezone


class UserProfile(models.Model):
    TIER_QUOTA_DEFAULTS = {
        "FREE": 30,
        "PRO": 500,
        "ADMIN": 999999,
    }
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

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self._state.adding:
            if (
                self.daily_quota_limit == self.TIER_QUOTA_DEFAULTS["FREE"]
                and self.plan_tier in self.TIER_QUOTA_DEFAULTS
            ):
                self.daily_quota_limit = self.TIER_QUOTA_DEFAULTS[self.plan_tier]
        elif self.pk and (update_fields is None or "plan_tier" in update_fields):
            old_tier = UserProfile.objects.filter(pk=self.pk).values_list("plan_tier", flat=True).first()
            if old_tier and old_tier != self.plan_tier:
                old_default = self.TIER_QUOTA_DEFAULTS.get(old_tier)
                new_default = self.TIER_QUOTA_DEFAULTS.get(self.plan_tier)
                if new_default and self.daily_quota_limit == old_default:
                    self.daily_quota_limit = new_default
                    if update_fields is not None:
                        kwargs["update_fields"] = list(set(update_fields) | {"daily_quota_limit"})
        super().save(*args, **kwargs)

    def check_and_reset_quota(self) -> None:
        """Gün değiştiğinde günlük kullanım sayacını atomik olarak sıfırlar."""
        today = timezone.localdate()
        if self.quota_reset_date < today:
            if not self.pk:
                self.daily_quota_used = 0
                self.quota_reset_date = today
                return
            updated = UserProfile.objects.filter(
                pk=self.pk, quota_reset_date__lt=today
            ).update(daily_quota_used=0, quota_reset_date=today)
            if updated:
                self.daily_quota_used = 0
                self.quota_reset_date = today
            else:
                self.refresh_from_db(fields=["daily_quota_used", "quota_reset_date"])

    def can_ask_question(self) -> bool:
        """Kullanıcının kalan soru hakkı olup olmadığını kontrol eder."""
        self.check_and_reset_quota()
        if self.plan_tier == "ADMIN":
            return True
        return self.daily_quota_used < self.daily_quota_limit

    def consume_quota(self) -> bool:
        """1 adet soru kotasını atomik SQL artışı ile harcar."""
        from django.db import transaction
        from django.db.models import F

        self.check_and_reset_quota()
        if not self.pk:
            return False

        if self.plan_tier == "ADMIN":
            UserProfile.objects.filter(pk=self.pk).update(
                daily_quota_used=F("daily_quota_used") + 1
            )
            self.refresh_from_db(fields=["daily_quota_used"])
            return True

        with transaction.atomic():
            updated = UserProfile.objects.filter(
                pk=self.pk,
                daily_quota_used__lt=F("daily_quota_limit"),
            ).update(daily_quota_used=F("daily_quota_used") + 1)
            if not updated:
                return False
            self.refresh_from_db(fields=["daily_quota_used"])
            return True
