"""Teachers app."""

from django.db import models


class Teacher(models.Model):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='teacher_profile',
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='teachers',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'teachers'
        indexes = [
            models.Index(fields=['organization']),
        ]

    def __str__(self):
        return self.user.get_full_name()
