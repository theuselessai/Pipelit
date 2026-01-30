from django.db import models


class SystemConfig(models.Model):
    default_llm_model = models.ForeignKey(
        "credentials.LLMModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    default_timezone = models.CharField(max_length=50, default="UTC")
    max_workflow_execution_seconds = models.IntegerField(default=600)
    confirmation_timeout_seconds = models.IntegerField(default=300)
    sandbox_code_execution = models.BooleanField(default=False)
    feature_flags = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Configuration"
        verbose_name_plural = "System Configuration"

    def __str__(self):
        return "System Configuration"

    def save(self, *args, **kwargs):
        # Enforce singleton
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
