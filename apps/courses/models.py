"""Courses app — course management with teacher/group assignments."""

from django.db import models


class CourseStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'


class SessionType(models.TextChoices):
    LECTURE = 'LECTURE', 'Lecture'
    LAB = 'LAB', 'Lab'
    TUTORIAL = 'TUTORIAL', 'Tutorial'


class Course(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='courses',
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='courses',
    )
    groups = models.ManyToManyField(
        'groups.Group',
        related_name='courses',
        blank=True,
    )
    academic_year = models.CharField(max_length=20, blank=True, help_text='e.g. 2026/2027')
    semester = models.CharField(max_length=50, blank=True, help_text='e.g. Fall, Spring')
    department = models.CharField(max_length=100, blank=True)
    level = models.CharField(max_length=50, blank=True, help_text='e.g. 1st Year, 2nd Year')
    status = models.CharField(
        max_length=20,
        choices=CourseStatus.choices,
        default=CourseStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'courses'
        unique_together = [('organization', 'code')]
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['teacher']),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'


class Schedule(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='schedules',
    )
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='schedules',
    )
    session_type = models.CharField(
        max_length=20,
        choices=SessionType.choices,
        default=SessionType.LECTURE,
    )
    location = models.ForeignKey(
        'locations.AttendanceLocation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='schedules',
    )
    day_of_week = models.IntegerField(help_text='0=Monday, 6=Sunday')
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'schedules'
        indexes = [
            models.Index(fields=['course', 'day_of_week']),
        ]

    def __str__(self):
        return f'{self.course.code} {self.session_type} on day {self.day_of_week}'
