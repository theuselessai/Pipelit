from django.contrib import admin

from .models import (
    BaseCredentials,
    GitCredential,
    LLMProviderCredentials,
    TelegramCredential,
    ToolCredential,
)


@admin.register(BaseCredentials)
class BaseCredentialsAdmin(admin.ModelAdmin):
    list_display = ("name", "credential_type", "user_profile", "created_at")
    list_filter = ("credential_type",)


@admin.register(GitCredential)
class GitCredentialAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "provider", "credential_type", "username")


@admin.register(LLMProviderCredentials)
class LLMProviderCredentialsAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "provider_type", "base_url")


@admin.register(TelegramCredential)
class TelegramCredentialAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "allowed_user_ids")


@admin.register(ToolCredential)
class ToolCredentialAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "tool_type")
