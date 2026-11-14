"""
Forms for user authentication, registration, and profile management.
"""

from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from apps.accounts.models import UserProfile

User = get_user_model()


class UserRegistrationForm(forms.Form):
    """
    Form for registering a new user with optional Riot ID fields.
    """
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Kullanıcı adı",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            "placeholder": "E-posta (isteğe bağlı)",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Şifre (en az 6 karakter)",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Şifre tekrarı",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    riot_game_name = forms.CharField(
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Riot Oyuncu Adı (örn: Agonist)",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    riot_tag_line = forms.CharField(
        max_length=16,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Riot Etiketi (örn: TR1)",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    riot_region = forms.ChoiceField(
        choices=[
            ("TR1", "TR1 (Türkiye)"),
            ("EUW1", "EUW1 (Batı Avrupa)"),
            ("EUN1", "EUN1 (Kuzey-Doğu)"),
            ("NA1", "NA1 (Kuzey Amerika)"),
            ("KR", "KR (Kore)"),
        ],
        required=False,
        initial="TR1",
        widget=forms.Select(attrs={
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-2.5 py-2 text-xs text-slate-200 outline-none",
        }),
    )

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise ValidationError("Kullanıcı adı boş bırakılamaz.")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Bu kullanıcı adı zaten alınmış.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:
            if password != confirm_password:
                self.add_error("confirm_password", "Şifreler birbiriyle eşleşmiyor.")
            if len(password) < 6:
                self.add_error("password", "Şifre en az 6 karakter olmalıdır.")

        return cleaned_data

    def save(self):
        """Creates the user and populates profile fields."""
        username = self.cleaned_data["username"]
        email = self.cleaned_data.get("email", "")
        password = self.cleaned_data["password"]

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        profile, _ = UserProfile.objects.get_or_create(user=user)
        riot_game_name = self.cleaned_data.get("riot_game_name", "").strip()
        riot_tag_line = self.cleaned_data.get("riot_tag_line", "").strip()
        riot_region = self.cleaned_data.get("riot_region", "TR1") or "TR1"

        if riot_game_name:
            profile.riot_game_name = riot_game_name
        if riot_tag_line:
            profile.riot_tag_line = riot_tag_line
        profile.riot_region = riot_region
        profile.save(update_fields=["riot_game_name", "riot_tag_line", "riot_region", "updated_at"])

        return user


class UserLoginForm(forms.Form):
    """
    Form for user login credentials.
    """
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Kullanıcı adı",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Şifre",
            "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username", "").strip()
        password = cleaned_data.get("password", "")

        if username and password:
            self.user = authenticate(username=username, password=password)
            if self.user is None:
                raise ValidationError("Geçersiz kullanıcı adı veya şifre.")
        return cleaned_data


class UserProfileUpdateForm(forms.ModelForm):
    """
    Form for updating Riot ID and user preferences.
    """
    class Meta:
        model = UserProfile
        fields = ["riot_game_name", "riot_tag_line", "riot_region", "preferred_lang"]
        widgets = {
            "riot_game_name": forms.TextInput(attrs={
                "placeholder": "Riot Oyuncu Adı",
                "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
            }),
            "riot_tag_line": forms.TextInput(attrs={
                "placeholder": "Etiket (#)",
                "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400 outline-none",
            }),
            "riot_region": forms.Select(attrs={
                "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-2.5 py-2 text-xs text-slate-200 outline-none",
            }),
            "preferred_lang": forms.Select(attrs={
                "class": "w-full bg-[#121722] border border-[#222d42] focus:border-[#f0c374] rounded-xl px-2.5 py-2 text-xs text-slate-200 outline-none",
            }),
        }
