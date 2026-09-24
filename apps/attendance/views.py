"""
Attendance views.
"""

import logging
import csv
from django.utils import timezone
from django.http import HttpResponse
from rest_framework import generics, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.accounts.permissions import (
    IsStudent, IsOrganizationAdmin, IsDoctor, IsTeachingAssistant,
    IsDoctorOrAssistant, IsTeacherOrAdmin,
)
from apps.audit.service import audit
from apps.audit.models import AuditAction

from .models import AttendanceSession, AttendanceRecord, SessionStatus
from .serializers import (
    AttendanceSessionSerializer, CheckInRequestSerializer, AttendanceRecordSerializer,
    AdHocSessionStartSerializer,
)
from .verification import AttendanceVerificationService, VerificationError
from .services import (
    get_doctor_today_work, get_ta_today_work, get_student_today_work,
    get_org_now_and_today, open_occurrence_session, close_attendance_session,
    create_and_open_adhoc_session,
)

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class TodayWorkView(APIView):
    """
    Role-specific daily workflow API (`GET /attendance/today/`).
    Calculates today's occurrences/sessions using the organization's timezone.
    """

    def get(self, request):
        user = request.user
        if user.role == Role.DOCTOR:
            data = get_doctor_today_work(user)
        elif user.role == Role.TEACHING_ASSISTANT:
            data = get_ta_today_work(user)
        elif user.role == Role.STUDENT:
            data = get_student_today_work(user)
        elif user.role in [Role.ADMIN, Role.SUPERADMIN]:
            # For admin, return combined work
            data = {
                'doctor_work': get_doctor_today_work(user),
                'ta_work': get_ta_today_work(user),
            }
        else:
            data = []

        return Response(data, status=status.HTTP_200_OK)


class OpenOccurrenceSessionView(APIView):
    """
    Opens an attendance session for a scheduled SessionOccurrence.
    Enforces role authorization (Doctor / TA only) & automatic location capture payload.
    """
    permission_classes = [IsDoctorOrAssistant]

    def post(self, request, occurrence_id):
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        accuracy = request.data.get('location_accuracy_meters') or request.data.get('accuracy_m')
        captured_at = request.data.get('location_captured_at') or request.data.get('captured_at')
        duration = int(request.data.get('duration_minutes', 60))
        late_after = int(request.data.get('late_after_minutes', 15))
        radius = request.data.get('radius_meters')

        try:
            session = open_occurrence_session(
                user=request.user,
                occurrence_id=occurrence_id,
                latitude=lat,
                longitude=lng,
                location_accuracy_meters=accuracy,
                location_captured_at=captured_at,
                duration_minutes=duration,
                late_after_minutes=late_after,
                radius_meters=radius,
            )
        except ValueError as exc:
            code = exc.args[1] if len(exc.args) > 1 else 'BAD_REQUEST'
            return Response({'detail': exc.args[0], 'code': code}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AttendanceSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class AdHocSessionStartView(APIView):
    """
    Creates an ad-hoc SessionOccurrence and opens its AttendanceSession atomically.
    `POST /attendance/occurrences/ad-hoc/start/`
    """
    permission_classes = [IsDoctorOrAssistant]

    def post(self, request):
        serializer = AdHocSessionStartSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            session = create_and_open_adhoc_session(
                user=request.user,
                course_offering_id=data['course_offering_id'],
                group_id=data.get('group_id'),
                session_type=data.get('session_type', 'LECTURE'),
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                location_accuracy_meters=data.get('location_accuracy_meters'),
                location_captured_at=data.get('location_captured_at'),
                duration_minutes=int(request.data.get('duration_minutes', 60)),
                late_after_minutes=int(request.data.get('late_after_minutes', 15)),
                radius_meters=data.get('radius_meters', 50.0),
            )
        except ValueError as exc:
            code = exc.args[1] if len(exc.args) > 1 else 'BAD_REQUEST'
            return Response({'detail': exc.args[0], 'code': code}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AttendanceSessionSerializer(session).data, status=status.HTTP_201_CREATED)



class SessionCloseView(APIView):
    """Closes an active attendance session permanently. NO REOPEN."""
    permission_classes = [IsDoctorOrAssistant]

    def post(self, request, pk):
        try:
            session = close_attendance_session(user=request.user, session_id=pk)
        except ValueError as exc:
            code = exc.args[1] if len(exc.args) > 1 else 'BAD_REQUEST'
            return Response({'detail': exc.args[0], 'code': code}, status=status.HTTP_400_BAD_REQUEST)

        audit(
            action=AuditAction.SESSION_CLOSED,
            actor=request.user,
            organization=request.user.organization,
            target_type='AttendanceSession',
            target_id=session.id,
        )
        return Response({'detail': 'Session closed successfully'})


class SessionDeleteView(APIView):
    """Admin or owner deletes a session completely."""
    permission_classes = [IsTeacherOrAdmin]

    def delete(self, request, pk):
        try:
            session = AttendanceSession.objects.get(
                pk=pk,
                organization=request.user.organization,
            )
        except AttendanceSession.DoesNotExist:
            return Response({'detail': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        AttendanceRecord.objects.filter(session=session).delete()
        session_id = session.id
        session.delete()

        audit(
            action=AuditAction.SESSION_DELETED,
            actor=request.user,
            organization=request.user.organization,
            target_type='AttendanceSession',
            target_id=session_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChallengeRequestView(APIView):
    """Student requests challenge token."""
    permission_classes = [IsStudent]

    def post(self, request, session_id):
        device_id = request.data.get('device_id')
        if not device_id:
            return Response({'detail': 'device_id required'}, status=status.HTTP_400_BAD_REQUEST)

        student = request.user.student_profile
        svc = AttendanceVerificationService(student, get_client_ip(request))

        try:
            challenge = svc.issue_challenge(device_id=device_id, session_id=session_id)
        except VerificationError as exc:
            return Response(
                {'detail': exc.message, 'code': exc.code},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            'challenge_token': challenge.challenge_token,
            'expires_at': challenge.expires_at,
        })


class CheckInView(APIView):
    """Student submits attendance."""
    permission_classes = [IsStudent]

    def post(self, request, session_id):
        serializer = CheckInRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        student = request.user.student_profile
        svc = AttendanceVerificationService(student, get_client_ip(request))

        try:
            record = svc.verify(
                session_id=session_id,
                device_id=data['device_id'],
                challenge_token=data['challenge_token'],
                signature_b64=data['signature'],
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                location_accuracy=data.get('location_accuracy'),
                location_timestamp=data.get('location_timestamp'),
                mock_location=data.get('mock_location', False),
            )
        except VerificationError as exc:
            audit(
                action=AuditAction.ATTENDANCE_REJECTED,
                actor=request.user,
                organization=request.user.organization,
                metadata={'code': exc.code, 'session_id': session_id},
                ip_address=get_client_ip(request),
            )
            return Response(
                {'detail': exc.message, 'code': exc.code},
                status=status.HTTP_400_BAD_REQUEST
            )

        from .signals import broadcast_attendance_record
        broadcast_attendance_record(record)

        return Response(
            AttendanceRecordSerializer(record).data,
            status=status.HTTP_201_CREATED
        )


class SessionRecordsView(generics.ListAPIView):
    """Scoped access to session attendance records."""
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        session_id = self.kwargs['pk']
        user = self.request.user

        qs = AttendanceRecord.objects.filter(
            session__id=session_id,
            session__organization=user.organization,
        ).select_related('student__user', 'session__occurrence__course_offering__course').order_by('verified_at')

        # Scope enforcement
        if user.role == Role.DOCTOR:
            qs = qs.filter(session__occurrence__course_offering__doctor__user=user)
        elif user.role == Role.TEACHING_ASSISTANT:
            qs = qs.filter(session__occurrence__group__teaching_assistant__user=user)

        return qs


class ManualAttendanceOverrideView(APIView):
    """
    Doctor/TA/Admin manually marks PRESENT, LATE, EXCUSED, or CHEATING for a student.
    Fully audited with reason.
    """
    permission_classes = [IsDoctorOrAssistant]

    def post(self, request, pk):
        student_id = request.data.get('student_id')
        status_val = request.data.get('status', 'LATE')
        reason = request.data.get('reason', '')

        if not student_id:
            return Response({'detail': 'student_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        if status_val not in ['PRESENT', 'LATE', 'EXCUSED', 'CHEATING']:
            return Response(
                {'detail': 'Invalid status for manual correction. Must be PRESENT, LATE, EXCUSED, or CHEATING'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            session = AttendanceSession.objects.select_related(
                'occurrence__course_offering__doctor__user',
                'occurrence__group__teaching_assistant__user'
            ).get(pk=pk, organization=request.user.organization)
        except AttendanceSession.DoesNotExist:
            return Response({'detail': 'Attendance session not found'}, status=status.HTTP_404_NOT_FOUND)

        # CLOSED/EXPIRED means collection is finished, not that authorized staff
        # corrections are forbidden. Students may no longer submit attendance,
        # but staff retain the right to reconcile or correct a record after closure.
        if session.status not in [SessionStatus.ACTIVE, SessionStatus.CLOSED, SessionStatus.EXPIRED]:
            return Response(
                {'detail': 'Manual attendance correction is only allowed for active, closed, or expired sessions'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _, today_date, _ = get_org_now_and_today(request.user.organization)
        if session.occurrence.scheduled_date != today_date:
            return Response(
                {'detail': 'Attendance corrections are limited to today\'s sessions'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Scoped authorization check
        if request.user.role == Role.DOCTOR:
            if not session.occurrence.course_offering.doctor or session.occurrence.course_offering.doctor.user != request.user:
                return Response({'detail': 'Not authorized for this course offering'}, status=status.HTTP_403_FORBIDDEN)
        elif request.user.role == Role.TEACHING_ASSISTANT:
            if not session.occurrence.group or not session.occurrence.group.teaching_assistant or session.occurrence.group.teaching_assistant.user != request.user:
                return Response({'detail': 'Not authorized for this group'}, status=status.HTTP_403_FORBIDDEN)

        from apps.students.models import Student
        try:
            student = Student.objects.get(pk=student_id, organization=request.user.organization)
        except Student.DoesNotExist:
            return Response({'detail': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

        old_record = AttendanceRecord.objects.filter(session=session, student=student).first()
        old_status = old_record.status if old_record else None

        record, created = AttendanceRecord.objects.update_or_create(
            session=session,
            student=student,
            defaults={
                'status': status_val,
                'verified_at': timezone.now(),
            }
        )

        audit(
            action=AuditAction.ATTENDANCE_ACCEPTED,
            actor=request.user,
            organization=request.user.organization,
            target_type='AttendanceRecord',
            target_id=record.id,
            metadata={
                'manual_override': True,
                'session_id': session.id,
                'student_id': student.student_id,
                'old_status': old_status,
                'new_status': status_val,
                'reason': reason,
            },
        )

        from .signals import broadcast_attendance_record
        broadcast_attendance_record(record)

        return Response(
            AttendanceRecordSerializer(record).data,
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED
        )


class StudentAttendanceHistoryView(generics.ListAPIView):
    """Student views their own attendance history."""
    permission_classes = [IsStudent]
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        student = getattr(self.request.user, 'student_profile', None)
        if not student:
            return AttendanceRecord.objects.none()
        return AttendanceRecord.objects.filter(
            student=student
        ).select_related('session__occurrence__course_offering__course').order_by('-verified_at')


class SessionListCreateView(generics.ListAPIView):
    """List attendance sessions (Admin/Doctor/TA)."""
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = AttendanceSessionSerializer

    def get_queryset(self):
        user = self.request.user
        qs = AttendanceSession.objects.filter(
            organization=user.organization
        ).select_related('occurrence__course_offering__course', 'occurrence__group').order_by('-created_at')

        if user.role == Role.DOCTOR:
            qs = qs.filter(occurrence__course_offering__doctor__user=user)
        elif user.role == Role.TEACHING_ASSISTANT:
            qs = qs.filter(occurrence__group__teaching_assistant__user=user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs
