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

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if hasattr(self, 'teaching_assistant') and self.teaching_assistant and hasattr(self, 'course_offering') and self.course_offering:
            if self.teaching_assistant.organization_id != self.course_offering.course.organization_id:
                raise ValidationError({'teaching_assistant': "Teaching Assistant and Group must belong to the same organization."})

    def save(self, *args, **kwargs):
        self.full_clean()
        is_new = self.pk is None
        old_ta_id = None
        if not is_new:
            try:
                old_ta_id = Group.objects.get(pk=self.pk).teaching_assistant_id
            except Group.DoesNotExist:
                pass
                
        super().save(*args, **kwargs)
        
        if not is_new and old_ta_id != self.teaching_assistant_id:
            from apps.courses.models import Schedule
            Schedule.objects.filter(group=self).update(teaching_assistant=self.teaching_assistant)

    def __str__(self):
        return f'{self.course_offering.course.code} — {self.name}'
