"""
Staff app — Doctor and Teaching Assistant profiles.
"""

from django.db import models


class Doctor(models.Model):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='doctor_profile',
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='doctors',
    )
    department = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=50, blank=True, help_text='e.g. Prof., Dr.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'doctors'
        indexes = [
            models.Index(fields=['organization']),
        ]

    def __str__(self):
        return f'{self.title} {self.user.get_full_name()}'.strip()


class TeachingAssistant(models.Model):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='ta_profile',
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='teaching_assistants',
    )
    department = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'teaching_assistants'
        indexes = [
            models.Index(fields=['organization']),
        ]

    def __str__(self):
        return f'TA {self.user.get_full_name()}'
