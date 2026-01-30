from django.contrib import admin

from .models import SystemConfig


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ("default_timezone", "max_workflow_execution_seconds", "sandbox_code_execution")

    def has_add_permission(self, request):
        return not SystemConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
