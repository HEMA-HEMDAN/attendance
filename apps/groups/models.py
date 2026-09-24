"""Groups app — sections/groups under course offerings."""

from django.db import models


class GroupStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'


class Group(models.Model):
    course_offering = models.ForeignKey(
        'courses.CourseOffering',
        on_delete=models.CASCADE,
        related_name='groups',
    )
    name = models.CharField(max_length=100, help_text='e.g. Group A, Section 1')
    teaching_assistant = models.ForeignKey(
        'staff.TeachingAssistant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_groups',
    )
    status = models.CharField(
        max_length=20,
        choices=GroupStatus.choices,
        default=GroupStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'groups'
        unique_together = [('course_offering', 'name')]
        indexes = [
            models.Index(fields=['course_offering', 'status']),
            models.Index(fields=['teaching_assistant']),
        ]

    def __str__(self):
        return f'{self.course_offering.course.code} — {self.name}'
