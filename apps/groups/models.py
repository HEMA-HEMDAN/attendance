"""Groups app — organizational groupings of students."""

from django.db import models


class GroupStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'


class Group(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='groups',
    )
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=GroupStatus.choices,
        default=GroupStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'groups'
        unique_together = [('organization', 'name')]
        indexes = [
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f'{self.organization.name} / {self.name}'
