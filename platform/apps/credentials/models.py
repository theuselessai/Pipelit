from django.db import models
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField


class BaseCredentials(models.Model):
    class CredentialType(models.TextChoices):
        GIT = "git", "Git"
        LLM = "llm", "LLM Provider"
        TELEGRAM = "telegram", "Telegram"
        TOOL = "tool", "Tool"

    user_profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    name = models.CharField(max_length=255)
    credential_type = models.CharField(max_length=20, choices=CredentialType.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "base credentials"

    def __str__(self):
        return f"{self.name} ({self.credential_type})"


class GitCredential(models.Model):
    class GitProvider(models.TextChoices):
        GITHUB = "github", "GitHub"
        GITLAB = "gitlab", "GitLab"
        BITBUCKET = "bitbucket", "Bitbucket"

    class GitCredentialType(models.TextChoices):
        SSH_KEY = "ssh_key", "SSH Key"
        TOKEN = "token", "Token"
        APP = "app", "App"

    base_credentials = models.OneToOneField(
        BaseCredentials,
        on_delete=models.CASCADE,
        related_name="git_credential",
    )
    provider = models.CharField(max_length=20, choices=GitProvider.choices)
    credential_type = models.CharField(max_length=20, choices=GitCredentialType.choices)
    ssh_private_key = EncryptedTextField(blank=True, default="")
    access_token = EncryptedCharField(max_length=500, blank=True, default="")
    username = models.CharField(max_length=255, blank=True, default="")
    webhook_secret = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"Git ({self.provider}) - {self.base_credentials.name}"


class LLMProvider(models.Model):
    class ProviderType(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        OPENAI_COMPATIBLE = "openai_compatible", "OpenAI Compatible"

    name = models.CharField(max_length=255)
    provider_type = models.CharField(max_length=30, choices=ProviderType.choices)

    def __str__(self):
        return self.name


class LLMModel(models.Model):
    provider = models.ForeignKey(
        LLMProvider,
        on_delete=models.CASCADE,
        related_name="models",
    )
    model_name = models.CharField(max_length=255)
    default_temperature = models.FloatField(default=0.7)
    context_window = models.IntegerField(default=4096)

    def __str__(self):
        return f"{self.provider.name}/{self.model_name}"


class LLMProviderCredentials(models.Model):
    base_credentials = models.OneToOneField(
        BaseCredentials,
        on_delete=models.CASCADE,
        related_name="llm_credential",
    )
    provider = models.ForeignKey(
        LLMProvider,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    api_key = EncryptedCharField(max_length=500)
    base_url = models.URLField(blank=True, default="")

    class Meta:
        verbose_name_plural = "LLM provider credentials"

    def __str__(self):
        return f"LLM ({self.provider.name}) - {self.base_credentials.name}"


class TelegramCredential(models.Model):
    base_credentials = models.OneToOneField(
        BaseCredentials,
        on_delete=models.CASCADE,
        related_name="telegram_credential",
    )
    bot_token = EncryptedCharField(max_length=500)
    allowed_user_ids = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Comma-separated Telegram user IDs",
    )

    def __str__(self):
        return f"Telegram - {self.base_credentials.name}"


class ToolCredential(models.Model):
    class ToolType(models.TextChoices):
        SEARXNG = "searxng", "SearXNG"
        BROWSER = "browser", "Browser"
        API = "api", "API"

    base_credentials = models.OneToOneField(
        BaseCredentials,
        on_delete=models.CASCADE,
        related_name="tool_credential",
    )
    tool_type = models.CharField(max_length=20, choices=ToolType.choices)
    config = models.JSONField(
        default=dict,
        help_text="Tool-specific config (sensitive fields encrypted at app layer)",
    )

    def __str__(self):
        return f"Tool ({self.tool_type}) - {self.base_credentials.name}"
