"""
Courses app — AcademicYear, Semester, Course, CourseOffering, Schedule, ScheduleException.
"""

from django.db import models


class SessionType(models.TextChoices):
    LECTURE = 'LECTURE', 'Lecture'
    LAB = 'LAB', 'Lab'
    TUTORIAL = 'TUTORIAL', 'Tutorial'


class CourseOfferingStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'


class ExceptionType(models.TextChoices):
    CANCELLED = 'CANCELLED', 'Cancelled'
    MOVED = 'MOVED', 'Moved'
    SPECIAL = 'SPECIAL', 'Special'


class AcademicYear(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='academic_years',
    )
    name = models.CharField(max_length=100, help_text='e.g. 2026/2027')
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academic_years'
        unique_together = [('organization', 'name')]
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.name} ({self.organization.name})'


class Semester(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='semesters',
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name='semesters',
    )
    name = models.CharField(max_length=100, help_text='e.g. Fall, Spring, Summer')
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'semesters'
        unique_together = [('academic_year', 'name')]
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.academic_year.name} — {self.name}'


class Course(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='courses',
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    department = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'courses'
        unique_together = [('organization', 'code')]
        indexes = [
            models.Index(fields=['organization', 'code']),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'


class CourseOffering(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='offerings',
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name='course_offerings',
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.CASCADE,
        related_name='course_offerings',
    )
    doctor = models.ForeignKey(
        'staff.Doctor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='course_offerings',
        help_text='Doctor owner of this course offering',
    )
    status = models.CharField(
        max_length=20,
        choices=CourseOfferingStatus.choices,
        default=CourseOfferingStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'course_offerings'
        unique_together = [('course', 'academic_year', 'semester')]
        indexes = [
            models.Index(fields=['doctor', 'status']),
            models.Index(fields=['academic_year', 'semester']),
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if hasattr(self, 'doctor') and self.doctor and hasattr(self, 'course') and self.course:
            if self.doctor.organization_id != self.course.organization_id:
                raise ValidationError({'doctor': "Doctor and Course Offering must belong to the same organization."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.course.code} ({self.semester})'


class Schedule(models.Model):
    course_offering = models.ForeignKey(
        CourseOffering,
        on_delete=models.CASCADE,
        related_name='schedules',
    )
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='schedules',
        help_text='Required for LAB and TUTORIAL; null for LECTURE',
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
    room_label = models.CharField(max_length=255, blank=True)
    day_of_week = models.IntegerField(help_text='0=Monday, 6=Sunday')
    start_time = models.TimeField()
    end_time = models.TimeField()
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'schedules'
        indexes = [
            models.Index(fields=['course_offering', 'day_of_week', 'is_active']),
            models.Index(fields=['group', 'day_of_week', 'is_active']),
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        errors = {}
        if self.group and self.course_offering:
            if self.group.course_offering_id != self.course_offering_id:
                errors['group'] = f"Group '{self.group.name}' does not belong to course offering '{self.course_offering}'."
        if self.location and self.course_offering:
            if self.location.organization_id != self.course_offering.course.organization_id:
                errors['location'] = "Attendance location and course offering must belong to the same organization."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        group_str = f' / {self.group.name}' if self.group else ''
        return f'{self.course_offering.course.code}{group_str} {self.session_type} Day:{self.day_of_week}'


class ScheduleException(models.Model):
    schedule = models.ForeignKey(
        Schedule,
        on_delete=models.CASCADE,
        related_name='exceptions',
    )
    date = models.DateField()
    exception_type = models.CharField(
        max_length=20,
        choices=ExceptionType.choices,
        default=ExceptionType.CANCELLED,
    )
    reason = models.CharField(max_length=255, blank=True)
    new_start_time = models.TimeField(null=True, blank=True)
    new_end_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'schedule_exceptions'
        unique_together = [('schedule', 'date')]

    def __str__(self):
        return f'Exception {self.exception_type} for schedule {self.schedule_id} on {self.date}'
