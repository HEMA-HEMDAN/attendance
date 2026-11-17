"""
Audit app.

Records important operations across the system for security, compliance, and debugging.
Does NOT store sensitive biometric data.
"""

from django.db import models


class AuditAction(models.TextChoices):
    # Student lifecycle
    STUDENT_CREATED = 'STUDENT_CREATED', 'Student Created'
    STUDENT_UPDATED = 'STUDENT_UPDATED', 'Student Updated'
    STUDENT_DISABLED = 'STUDENT_DISABLED', 'Student Disabled'
    STUDENT_IMPORTED = 'STUDENT_IMPORTED', 'Student Imported (CSV)'

    # Device lifecycle
    DEVICE_REGISTERED = 'DEVICE_REGISTERED', 'Device Registered'
    DEVICE_REVOKED = 'DEVICE_REVOKED', 'Device Revoked'
    DEVICE_BIOMETRIC_INVALIDATED = 'DEVICE_BIOMETRIC_INVALIDATED', 'Device Biometric Invalidated'

    # Session lifecycle
    SESSION_CREATED = 'SESSION_CREATED', 'Session Created'
    SESSION_OPENED = 'SESSION_OPENED', 'Session Opened'
    SESSION_CLOSED = 'SESSION_CLOSED', 'Session Closed'
    SESSION_REOPENED = 'SESSION_REOPENED', 'Session Reopened'
    SESSION_DELETED = 'SESSION_DELETED', 'Session Deleted'
    SESSION_EXPIRED = 'SESSION_EXPIRED', 'Session Expired'

    # Attendance
    ATTENDANCE_ACCEPTED = 'ATTENDANCE_ACCEPTED', 'Attendance Accepted'
    ATTENDANCE_REJECTED = 'ATTENDANCE_REJECTED', 'Attendance Rejected'

    # Verification failures
    BIOMETRIC_FAILED = 'BIOMETRIC_FAILED', 'Biometric Verification Failed'
    LOCATION_FAILED = 'LOCATION_FAILED', 'Location Verification Failed'
    CHALLENGE_INVALID = 'CHALLENGE_INVALID', 'Challenge Invalid'

    # Auth
    LOGIN_SUCCESS = 'LOGIN_SUCCESS', 'Login Success'
    LOGIN_FAILED = 'LOGIN_FAILED', 'Login Failed'


class AuditLog(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )

    # Who did the action (null for anonymous/system)
    actor = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )

    action = models.CharField(max_length=50, choices=AuditAction.choices)

    # The resource being acted on
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=100, blank=True)

    # Contextual metadata — no sensitive biometric data
    metadata = models.JSONField(default=dict)

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        indexes = [
            models.Index(fields=['organization', 'action']),
            models.Index(fields=['actor']),
            models.Index(fields=['created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f'{self.action} by {self.actor_id} @ {self.created_at}'
