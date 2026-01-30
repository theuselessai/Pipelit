from django.contrib import admin

from .models import (
    BaseCredentials,
    GitCredential,
    LLMModel,
    LLMProvider,
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


@admin.register(LLMProvider)
class LLMProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "provider_type")


@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    list_display = ("model_name", "provider", "default_temperature", "context_window")


@admin.register(LLMProviderCredentials)
class LLMProviderCredentialsAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "provider", "base_url")


@admin.register(TelegramCredential)
class TelegramCredentialAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "allowed_user_ids")


@admin.register(ToolCredential)
class ToolCredentialAdmin(admin.ModelAdmin):
    list_display = ("base_credentials", "tool_type")
