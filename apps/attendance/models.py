"""
Attendance app.

Core models:
  SessionOccurrence — a date-specific occurrence derived from a Weekly Schedule
  AttendanceSession — 1-to-1 operational session opened for an occurrence
  AttendanceRecord  — a single student's attendance record
  DeviceChallenge   — short-lived cryptographic challenge token
"""

from django.db import models
from django.utils import timezone


class OccurrenceType(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    AD_HOC = 'AD_HOC', 'Ad-Hoc'


class SessionOccurrenceStatus(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    ACTIVE = 'ACTIVE', 'Active'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class SessionStatus(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    ACTIVE = 'ACTIVE', 'Active'
    CLOSED = 'CLOSED', 'Closed'
    EXPIRED = 'EXPIRED', 'Expired'


class AttendanceStatus(models.TextChoices):
    PRESENT = 'PRESENT', 'Present'
    LATE = 'LATE', 'Late'
    EXCUSED = 'EXCUSED', 'Excused'
    CHEATING = 'CHEATING', 'Cheating / Invalid'


class SessionOccurrence(models.Model):
    """
    A date-based instance of a Weekly Schedule or an Ad-Hoc Session.
    Unique by (schedule, scheduled_date) for scheduled occurrences.
    """
    occurrence_type = models.CharField(
        max_length=20,
        choices=OccurrenceType.choices,
        default=OccurrenceType.SCHEDULED,
    )
    schedule = models.ForeignKey(
        'courses.Schedule',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='occurrences',
    )
    course_offering = models.ForeignKey(
        'courses.CourseOffering',
        on_delete=models.CASCADE,
        related_name='occurrences',
    )
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='occurrences',
    )
    scheduled_date = models.DateField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    session_type = models.CharField(
        max_length=20,
        choices=[('LECTURE', 'Lecture'), ('LAB', 'Lab'), ('TUTORIAL', 'Tutorial')],
        default='LECTURE',
    )
    status = models.CharField(
        max_length=20,
        choices=SessionOccurrenceStatus.choices,
        default=SessionOccurrenceStatus.SCHEDULED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'session_occurrences'
        unique_together = [('schedule', 'scheduled_date')]
        indexes = [
            models.Index(fields=['course_offering', 'scheduled_date']),
            models.Index(fields=['group', 'scheduled_date']),
            models.Index(fields=['scheduled_date', 'status']),
            models.Index(fields=['course_offering', 'occurrence_type']),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    (models.Q(occurrence_type='SCHEDULED') & models.Q(schedule__isnull=False)) |
                    (models.Q(occurrence_type='AD_HOC') & models.Q(schedule__isnull=True))
                ),
                name='valid_occurrence_schedule_constraint'
            )
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.occurrence_type == OccurrenceType.SCHEDULED and not self.schedule_id:
            raise ValidationError({'schedule': 'Scheduled occurrences require a schedule.'})
        if self.occurrence_type == OccurrenceType.AD_HOC and self.schedule_id:
            raise ValidationError({'schedule': 'Ad-hoc occurrences cannot have a schedule.'})

    def __str__(self):
        group_str = f' / {self.group.name}' if self.group else ''
        return f'{self.course_offering.course.code}{group_str} {self.session_type} on {self.scheduled_date} ({self.occurrence_type})'


class AttendanceSession(models.Model):
    """
    Operational attendance session created for a single SessionOccurrence.
    1-to-1 relationship with SessionOccurrence. NO REOPEN.
    """
    occurrence = models.OneToOneField(
        SessionOccurrence,
        on_delete=models.CASCADE,
        related_name='attendance_session',
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    opened_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='opened_sessions',
    )

    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_accuracy_meters = models.FloatField(
        null=True,
        blank=True,
        help_text="Reported GPS accuracy of the opener's device (metres)",
    )
    location_captured_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opener's location was captured",
    )
    radius_meters = models.FloatField(default=200.0)
    max_location_accuracy_meters = models.FloatField(
        default=100.0,
        help_text='Reject location data with accuracy worse than this value (metres)',
    )
    late_after_minutes = models.PositiveIntegerField(
        default=15,
        help_text='Minutes after session start after which attendance is LATE',
    )

    status = models.CharField(
        max_length=20,
        choices=SessionStatus.choices,
        default=SessionStatus.ACTIVE,
    )

    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_sessions'
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f'AttendanceSession {self.id} for Occurrence {self.occurrence_id} ({self.status})'

    @property
    def opened_at(self):
        return self.starts_at

    def is_active(self):
        now = timezone.now()
        return self.status == SessionStatus.ACTIVE and now < self.expires_at


class AttendanceRecord(models.Model):
    """
    A single student's attendance record within a session.
    UNIQUE(session, student) enforced at DB level.
    """
    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.PROTECT,
        related_name='records',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='attendance_records',
    )
    device = models.ForeignKey(
        'devices.Device',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_records',
    )

    status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
    )

    verified_at = models.DateTimeField(auto_now_add=True)

    submitted_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    submitted_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_accuracy_meters = models.FloatField(null=True, blank=True)
    distance_from_location_meters = models.FloatField(null=True, blank=True)

    mock_location_detected = models.BooleanField(default=False)
    device_challenge_verified = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_records'
        unique_together = [('session', 'student')]
        indexes = [
            models.Index(fields=['session', 'status']),
            models.Index(fields=['student']),
            models.Index(fields=['verified_at']),
        ]

    def __str__(self):
        return f'{self.student} — {self.status} @ session {self.session_id}'


class DeviceChallenge(models.Model):
    """
    Short-lived cryptographic challenge token.
    """
    device = models.ForeignKey(
        'devices.Device',
        on_delete=models.CASCADE,
        related_name='challenges',
    )
    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name='challenges',
    )

    challenge_token = models.CharField(max_length=128, unique=True)
    is_used = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'device_challenges'
        indexes = [
            models.Index(fields=['challenge_token']),
            models.Index(fields=['device', 'is_used']),
        ]

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at
