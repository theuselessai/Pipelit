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


class LLMProviderCredentials(models.Model):
    class ProviderType(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        OPENAI_COMPATIBLE = "openai_compatible", "OpenAI Compatible"

    base_credentials = models.OneToOneField(
        BaseCredentials,
        on_delete=models.CASCADE,
        related_name="llm_credential",
    )
    provider_type = models.CharField(
        max_length=30,
        choices=ProviderType.choices,
        default=ProviderType.OPENAI_COMPATIBLE,
    )
    api_key = EncryptedCharField(max_length=500)
    base_url = models.URLField(blank=True, default="")
    organization_id = models.CharField(max_length=255, blank=True, default="")
    custom_headers = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "LLM provider credentials"

    def __str__(self):
        return f"LLM ({self.provider_type}) - {self.base_credentials.name}"


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
