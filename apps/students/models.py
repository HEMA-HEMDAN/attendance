"""
Students app.

Students are provisioned by organization admins — they do NOT self-register.
Each student is linked to a User account (for login) and has an organization-scoped
student_id (external ID from the institution).
"""

from django.db import models


class StudentStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    ARCHIVED = 'ARCHIVED', 'Archived'


class Student(models.Model):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='student_profile',
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='students',
    )
    student_id = models.CharField(
        max_length=100,
        help_text='Organization-scoped external student identifier',
    )
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='students',
    )
    phone = models.CharField(max_length=30, blank=True)
    personal_email = models.EmailField(blank=True, null=True, help_text='Fallback Gmail for OTPs')
    department = models.CharField(max_length=100, blank=True)
    academic_level = models.CharField(max_length=50, blank=True, help_text='e.g. 1st Year')
    status = models.CharField(
        max_length=20,
        choices=StudentStatus.choices,
        default=StudentStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'students'
        unique_together = [('organization', 'student_id')]
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['group']),
        ]

    def __str__(self):
        return f'{self.student_id} — {self.user.get_full_name()}'
