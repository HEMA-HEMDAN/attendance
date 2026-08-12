"""
Attendance Verification Engine.

This service owns the final attendance decision.
It validates every aspect of an attendance request server-side.

Validation pipeline:
  1. Authentication          (handled by DRF — token required)
  2. Organization membership (student.organization == session.organization)
  3. Student active          (student.status == ACTIVE)
  4. Student enrollment      (student.group enrolled in session.course/group)
  5. Session exists          (session found by ID)
  6. Session active          (status == ACTIVE, not expired)
  7. Session not expired     (now < session.expires_at)
  8. Device authorized       (device belongs to student, status ACTIVE)
  9. Challenge verification  (server verifies RSA signature)
 10. Location available      (if session requires it)
 11. Location accuracy       (accuracy <= session policy)
 12. Inside radius           (haversine distance <= location.radius_meters)
 13. Mock-location signal    (logged, configurable enforcement)
 14. Timestamp freshness     (location timestamp < 60s old)
 15. Duplicate check         (UNIQUE constraint at DB level, pre-checked here)
 16. Create record           (transactional)
"""

import base64
import hashlib
import logging
import secrets
from datetime import timedelta

from django.db import transaction, IntegrityError
from django.utils import timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend

from apps.audit.service import audit
from apps.audit.models import AuditAction
from apps.locations.utils import haversine_distance, validate_coordinates
from .models import AttendanceSession, AttendanceRecord, DeviceChallenge, SessionStatus

logger = logging.getLogger(__name__)

# Maximum age of a location timestamp accepted by the server (seconds)
LOCATION_MAX_AGE_SECONDS = 60

# Challenge TTL (seconds)
CHALLENGE_TTL_SECONDS = 120


class VerificationError(Exception):
    """Raised when an attendance verification step fails."""

    def __init__(self, message: str, code: str, audit_action: str = None):
        self.message = message
        self.code = code
        self.audit_action = audit_action
        super().__init__(message)


class AttendanceVerificationService:
    """
    Stateless service. Each method is a validation step.
    Call verify() to run the full pipeline.
    """

    def __init__(self, student, request_ip: str = None):
        self.student = student
        self.request_ip = request_ip

    def issue_challenge(self, device_id: int, session_id: int) -> DeviceChallenge:
        """
        Issue a server-generated challenge for biometric/device verification.
        The mobile will:
          1. Unlock the private key with biometric auth
          2. Sign the challenge token
          3. Submit the signature with the attendance request
        """
        from apps.devices.models import Device

        # Validate device
        try:
            device = Device.objects.get(
                pk=device_id,
                student=self.student,
                status='ACTIVE',
            )
        except Device.DoesNotExist:
            raise VerificationError(
                'Device not found or not authorized',
                'DEVICE_NOT_FOUND',
                AuditAction.BIOMETRIC_FAILED,
            )

        # Validate session exists and is active
        try:
            session = AttendanceSession.objects.get(
                pk=session_id,
                organization=self.student.organization,
                status=SessionStatus.ACTIVE,
            )
        except AttendanceSession.DoesNotExist:
            raise VerificationError('Session not found or not active', 'SESSION_NOT_FOUND')

        if not session.is_active():
            raise VerificationError('Session has expired', 'SESSION_EXPIRED')

        # Expire old unused challenges for this device+session
        DeviceChallenge.objects.filter(
            device=device,
            session=session,
            is_used=False,
        ).update(is_used=True)

        challenge_token = secrets.token_hex(32)
        challenge = DeviceChallenge.objects.create(
            device=device,
            session=session,
            challenge_token=challenge_token,
            expires_at=timezone.now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        )
        return challenge

    @transaction.atomic
    def verify(
        self,
        session_id: int,
        device_id: int,
        challenge_token: str,
        signature_b64: str,
        latitude: float = None,
        longitude: float = None,
        location_accuracy: float = None,
        location_timestamp: float = None,  # Unix timestamp
        mock_location: bool = False,
    ) -> AttendanceRecord:
        """
        Run the full verification pipeline and create an attendance record.
        Raises VerificationError on any failure.
        """

        # ── 1. Get session ────────────────────────────────────────────
        try:
            session = AttendanceSession.objects.select_related(
                'course', 'group', 'organization'
            ).get(pk=session_id)
        except AttendanceSession.DoesNotExist:
            raise VerificationError('Session not found', 'SESSION_NOT_FOUND')

        # ── 2. Organization isolation ─────────────────────────────────
        if session.organization_id != self.student.organization_id:
            raise VerificationError('Not authorized for this session', 'ORG_MISMATCH')

        # ── 3. Student active ─────────────────────────────────────────
        if self.student.status != 'ACTIVE':
            raise VerificationError('Student account is not active', 'STUDENT_INACTIVE')

        # ── 4. Student enrollment (group match) ───────────────────────
        enrollment_qs = self.student.enrollments.filter(course_id=session.course_id)
        if session.group_id:
            enrollment_qs = enrollment_qs.filter(group_id=session.group_id)
            
        if not enrollment_qs.exists():
            raise VerificationError(
                'Student not enrolled in this session', 'ENROLLMENT_MISMATCH'
            )

        # ── 5. Session status ─────────────────────────────────────────
        if session.status != SessionStatus.ACTIVE:
            raise VerificationError(
                f'Session is {session.status.lower()}', 'SESSION_NOT_ACTIVE'
            )

        # ── 6. Session time ───────────────────────────────────────────
        now = timezone.now()
        if now >= session.expires_at:
            session.status = SessionStatus.EXPIRED
            session.save(update_fields=['status'])
            raise VerificationError('Session has expired', 'SESSION_EXPIRED')

        # ── 7. Device authorized ──────────────────────────────────────
        from apps.devices.models import Device
        try:
            device = Device.objects.get(
                pk=device_id,
                student=self.student,
                status='ACTIVE',
            )
        except Device.DoesNotExist:
            raise VerificationError(
                'Device not found or revoked. Contact your organization.',
                'DEVICE_NOT_AUTHORIZED',
                AuditAction.BIOMETRIC_FAILED,
            )

        if device.biometric_invalidated:
            raise VerificationError(
                'Biometric configuration has changed. Please re-register.',
                'BIOMETRIC_INVALIDATED',
                AuditAction.BIOMETRIC_FAILED,
            )

        # ── 8. Verify challenge/signature ─────────────────────────────
        device_challenge_verified = self._verify_challenge(
            device=device,
            challenge_token=challenge_token,
            signature_b64=signature_b64,
        )

        # ── 9. Location verification ──────────────────────────────────
        distance_m = None
        if session.location_required:
            if latitude is None or longitude is None:
                raise VerificationError(
                    'Location data is required for this session',
                    'LOCATION_REQUIRED',
                    AuditAction.LOCATION_FAILED,
                )

        distance_m = self._verify_location(
            session=session,
            latitude=latitude,
            longitude=longitude,
            location_accuracy=location_accuracy,
            location_timestamp=location_timestamp,
            mock_location=mock_location,
        ) if latitude is not None else None

        # ── 10. Duplicate check ───────────────────────────────────────
        if AttendanceRecord.objects.filter(session=session, student=self.student).exists():
            raise VerificationError(
                'Attendance already recorded for this session',
                'DUPLICATE_ATTENDANCE',
            )

        # ── 11. Determine status (PRESENT or LATE) ────────────────────
        late_cutoff = session.starts_at + timedelta(minutes=session.late_after_minutes)
        attendance_status = 'LATE' if now > late_cutoff else 'PRESENT'

        # ── 12. Create record ─────────────────────────────────────────
        try:
            record = AttendanceRecord.objects.create(
                session=session,
                student=self.student,
                device=device,
                status=attendance_status,
                submitted_latitude=latitude,
                submitted_longitude=longitude,
                location_accuracy_meters=location_accuracy,
                distance_from_location_meters=distance_m,
                mock_location_detected=mock_location,
                device_challenge_verified=device_challenge_verified,
            )
        except IntegrityError:
            # Race condition — another request created a record simultaneously
            raise VerificationError(
                'Attendance already recorded (concurrent request)',
                'DUPLICATE_ATTENDANCE',
            )

        # Update device last seen
        Device.objects.filter(pk=device.id).update(last_seen_at=now)

        # Audit
        audit(
            action=AuditAction.ATTENDANCE_ACCEPTED,
            actor=self.student.user,
            organization=self.student.organization,
            target_type='AttendanceRecord',
            target_id=record.id,
            metadata={
                'session_id': session_id,
                'status': attendance_status,
                'distance_m': distance_m,
                'mock_location': mock_location,
            },
            ip_address=self.request_ip,
        )

        return record

    def _verify_challenge(self, device, challenge_token: str, signature_b64: str) -> bool:
        """
        Verify that the mobile signed the challenge token with the device's private key.
        Returns True if verified, raises VerificationError on failure.
        """
        try:
            challenge = DeviceChallenge.objects.get(
                challenge_token=challenge_token,
                device=device,
            )
        except DeviceChallenge.DoesNotExist:
            audit(
                action=AuditAction.CHALLENGE_INVALID,
                actor=self.student.user,
                organization=self.student.organization,
                metadata={'reason': 'challenge not found'},
                ip_address=self.request_ip,
            )
            raise VerificationError(
                'Invalid challenge', 'CHALLENGE_INVALID', AuditAction.BIOMETRIC_FAILED
            )

        if not challenge.is_valid():
            raise VerificationError(
                'Challenge expired or already used', 'CHALLENGE_EXPIRED', AuditAction.BIOMETRIC_FAILED
            )

        try:
            public_key = serialization.load_pem_public_key(
                device.public_key.encode(), backend=default_backend()
            )
            signature = base64.b64decode(signature_b64)
            public_key.verify(
                signature,
                challenge_token.encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, Exception) as exc:
            logger.warning('Signature verification failed for device %s: %s', device.id, exc)
            challenge.is_used = True
            challenge.save(update_fields=['is_used'])
            audit(
                action=AuditAction.BIOMETRIC_FAILED,
                actor=self.student.user,
                organization=self.student.organization,
                metadata={'reason': 'signature_invalid'},
                ip_address=self.request_ip,
            )
            raise VerificationError(
                'Biometric verification failed', 'SIGNATURE_INVALID', AuditAction.BIOMETRIC_FAILED
            )

        # Mark challenge as used (single-use)
        challenge.is_used = True
        challenge.save(update_fields=['is_used'])
        return True

    def _verify_location(
        self,
        session: AttendanceSession,
        latitude: float,
        longitude: float,
        location_accuracy: float,
        location_timestamp: float,
        mock_location: bool,
    ) -> float:
        """
        Validate location data and return distance from session location in metres.
        Raises VerificationError on failure.
        """

        # Validate coordinate ranges
        if not validate_coordinates(latitude, longitude):
            raise VerificationError(
                'Invalid location coordinates', 'INVALID_COORDINATES', AuditAction.LOCATION_FAILED
            )

        # Timestamp freshness
        if location_timestamp is not None:
            import datetime
            location_time = datetime.datetime.fromtimestamp(
                location_timestamp, tz=datetime.timezone.utc
            )
            age_seconds = (timezone.now() - location_time).total_seconds()
            if age_seconds > LOCATION_MAX_AGE_SECONDS or age_seconds < -10:
                raise VerificationError(
                    'Location timestamp is stale or invalid',
                    'STALE_LOCATION',
                    AuditAction.LOCATION_FAILED,
                )

        # Accuracy check
        if location_accuracy is not None and session.max_location_accuracy_meters:
            if location_accuracy > session.max_location_accuracy_meters:
                raise VerificationError(
                    "Your current location isn't accurate enough",
                    'POOR_ACCURACY',
                    AuditAction.LOCATION_FAILED,
                )

        if session.latitude is None or session.longitude is None:
            # Session has no location requirement
            return None

        # Distance calculation (server-side)
        distance_m = haversine_distance(
            float(session.latitude), float(session.longitude),
            latitude, longitude,
        )

        if distance_m > session.radius_meters:
            audit(
                action=AuditAction.LOCATION_FAILED,
                actor=self.student.user,
                organization=self.student.organization,
                metadata={
                    'distance_m': round(distance_m, 1),
                    'radius_m': session.radius_meters,
                    'mock': mock_location,
                },
                ip_address=self.request_ip,
            )
            raise VerificationError(
                "You're outside the attendance area",
                'OUTSIDE_RADIUS',
                AuditAction.LOCATION_FAILED,
            )

        return round(distance_m, 1)
