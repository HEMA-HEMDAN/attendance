"""
Attendance app.

Core models:
  AttendanceSession — a single attendance event (created by a teacher)
  AttendanceRecord  — a single student's attendance within a session

Security invariants enforced here:
  - UNIQUE(session, student) prevents duplicate records at DB level
  - Server controls all timestamps (no client-provided attendance time)
  - Verification metadata is stored for auditing without storing biometric data
"""

from django.db import models
from django.utils import timezone


class SessionStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    CLOSED = 'CLOSED', 'Closed'
    EXPIRED = 'EXPIRED', 'Expired'


class AttendanceStatus(models.TextChoices):
    PRESENT = 'PRESENT', 'Present'
    LATE = 'LATE', 'Late'
    EXCUSED = 'EXCUSED', 'Excused'


class AttendanceSession(models.Model):
    """
    An attendance session is created by a teacher for a specific course+group.
    The server controls timing — client clocks are not trusted.
    """

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.PROTECT,
        related_name='sessions',
    )
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.PROTECT,
        related_name='sessions',
    )
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.PROTECT,
        related_name='sessions',
    )
    location = models.ForeignKey(
        'locations.AttendanceLocation',
        on_delete=models.PROTECT,
        related_name='sessions',
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=SessionStatus.choices,
        default=SessionStatus.ACTIVE,
    )

    # Server-controlled timing
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    # Session policy — configurable per session
    biometric_required = models.BooleanField(default=True)
    location_required = models.BooleanField(default=True)
    max_location_accuracy_meters = models.FloatField(
        default=50.0,
        help_text='Reject location data with accuracy worse than this value (metres)',
    )
    late_after_minutes = models.PositiveIntegerField(
        default=15,
        help_text='Minutes after session start after which attendance is LATE',
    )
    duration_minutes = models.PositiveIntegerField(default=60)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_sessions'
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['course', 'group']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f'Session {self.id} — {self.course} / {self.group} ({self.status})'

    def is_active(self):
        now = timezone.now()
        return self.status == SessionStatus.ACTIVE and now < self.expires_at


class AttendanceRecord(models.Model):
    """
    A single student's attendance within a session.
    UNIQUE(session, student) enforced at DB level to prevent duplicates.
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

    # Server-assigned timestamp — client timestamp is NOT used for the record
    verified_at = models.DateTimeField(auto_now_add=True)

    # Location verification metadata (stored for audit, not for re-verification)
    submitted_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    submitted_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_accuracy_meters = models.FloatField(null=True, blank=True)
    distance_from_location_meters = models.FloatField(null=True, blank=True)

    # Signals (not hard blockers for all policies, but stored for audit)
    mock_location_detected = models.BooleanField(default=False)

    # Biometric/device verification metadata
    # We store whether the challenge was verified — NOT any biometric data
    device_challenge_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_records'
        # CRITICAL: database-level duplicate protection
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
    A server-generated challenge for biometric/device verification.
    Short-lived (TTL enforced in verification service).

    Flow:
      1. Student requests challenge  -> server creates DeviceChallenge
      2. Mobile signs with private key after biometric auth
      3. Server verifies signature against stored public key
      4. Server marks challenge as used (single-use)
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
