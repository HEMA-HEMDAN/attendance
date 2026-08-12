"""Attendance views."""

import logging
from django.utils import timezone
from datetime import timedelta
from rest_framework import generics, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeacher, IsStudent, IsOrganizationAdmin, IsAdminOrTeacher
from apps.audit.service import audit
from apps.audit.models import AuditAction

from .models import AttendanceSession, AttendanceRecord, DeviceChallenge, SessionStatus
from .serializers import (
    AttendanceSessionSerializer, SessionCreateSerializer,
    CheckInRequestSerializer, AttendanceRecordSerializer,
)
from .verification import AttendanceVerificationService, VerificationError

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class SessionListCreateView(generics.ListCreateAPIView):
    """Teacher creates sessions; admin and teacher can list."""
    filter_backends = [filters.SearchFilter]
    search_fields = ['course__name', 'group__name']

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAdminOrTeacher()]
        return [IsTeacher()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return SessionCreateSerializer
        return AttendanceSessionSerializer

    def get_queryset(self):
        qs = AttendanceSession.objects.filter(
            organization=self.request.user.organization
        ).select_related('course', 'group', 'teacher__user').order_by('-created_at')

        if self.request.user.is_teacher:
            qs = qs.filter(teacher__user=self.request.user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs

    def perform_create(self, serializer):
        session = serializer.save()
        audit(
            action=AuditAction.SESSION_CREATED,
            actor=self.request.user,
            organization=self.request.user.organization,
            target_type='AttendanceSession',
            target_id=session.id,
            metadata={
                'course': session.course.name if session.course else None,
                'group': session.group.name if session.group else None,
            },
        )


class SessionCloseView(APIView):
    """Teacher closes their own session."""
    permission_classes = [IsTeacher]

    def post(self, request, pk):
        try:
            session = AttendanceSession.objects.get(
                pk=pk,
                teacher__user=request.user,
                organization=request.user.organization,
            )
        except AttendanceSession.DoesNotExist:
            return Response({'detail': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        if session.status != SessionStatus.ACTIVE:
            return Response(
                {'detail': f'Session is already {session.status.lower()}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        session.status = SessionStatus.CLOSED
        session.closed_at = timezone.now()
        session.save(update_fields=['status', 'closed_at'])

        audit(
            action=AuditAction.SESSION_CLOSED,
            actor=request.user,
            organization=request.user.organization,
            target_type='AttendanceSession',
            target_id=session.id,
        )
        return Response({'detail': 'Session closed successfully'})


class SessionReopenView(APIView):
    """Teacher reopens their own closed session."""
    permission_classes = [IsTeacher]

    def post(self, request, pk):
        try:
            session = AttendanceSession.objects.get(
                pk=pk,
                teacher__user=request.user,
                organization=request.user.organization,
            )
        except AttendanceSession.DoesNotExist:
            return Response({'detail': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        if session.status != SessionStatus.CLOSED:
            return Response(
                {'detail': f'Session cannot be reopened because it is {session.status.lower()}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        session.status = SessionStatus.ACTIVE
        session.closed_at = None
        if timezone.now() > session.expires_at:
            session.expires_at = timezone.now() + timedelta(minutes=session.duration_minutes)
        
        session.save(update_fields=['status', 'closed_at', 'expires_at'])

        audit(
            action=AuditAction.SESSION_REOPENED,
            actor=request.user,
            organization=request.user.organization,
            target_type='AttendanceSession',
            target_id=session.id,
        )
        return Response({'detail': 'Session reopened successfully'})


class SessionDeleteView(APIView):
    """Teacher or Admin deletes a session completely."""
    permission_classes = [IsAdminOrTeacher]

    def delete(self, request, pk):
        try:
            session = AttendanceSession.objects.get(
                pk=pk,
                organization=request.user.organization,
            )
        except AttendanceSession.DoesNotExist:
            return Response({'detail': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role in ['DOCTOR', 'TEACHING_ASSISTANT'] and session.teacher.user != request.user:
            return Response({'detail': 'You can only delete your own sessions'}, status=status.HTTP_403_FORBIDDEN)

        # Delete all records first due to PROTECT constraint
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
    """
    Student requests a challenge token.
    The mobile signs it with the device private key after biometric auth.
    """
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
    """
    Student submits attendance.
    The server runs the full verification pipeline and makes the final decision.
    """
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

        # Broadcast live update to teacher WebSocket (non-blocking)
        from .signals import broadcast_attendance_record
        broadcast_attendance_record(record)

        return Response(
            AttendanceRecordSerializer(record).data,
            status=status.HTTP_201_CREATED
        )


class SessionRecordsView(generics.ListAPIView):
    """Teacher/admin views records for a session."""
    permission_classes = [IsAdminOrTeacher]
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        session_id = self.kwargs['pk']
        return AttendanceRecord.objects.filter(
            session__id=session_id,
            session__organization=self.request.user.organization,
        ).select_related('student__user').order_by('verified_at')


class ManualAttendanceOverrideView(APIView):
    """
    Teacher/Admin manually marks or overrides attendance for a student in a session.
    """
    permission_classes = [IsAdminOrTeacher]

    def post(self, request, pk):
        student_id = request.data.get('student_id')
        status_val = request.data.get('status', 'PRESENT')

        if not student_id:
            return Response({'detail': 'student_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        if status_val not in ['PRESENT', 'LATE', 'EXCUSED', 'CHEATING']:
            return Response({'detail': 'Invalid status. Must be PRESENT, LATE, EXCUSED, or CHEATING'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = AttendanceSession.objects.get(
                pk=pk,
                organization=request.user.organization,
            )
        except AttendanceSession.DoesNotExist:
            return Response({'detail': 'Attendance session not found'}, status=status.HTTP_404_NOT_FOUND)

        from apps.students.models import Student
        try:
            student = Student.objects.get(
                pk=student_id,
                organization=request.user.organization,
            )
        except Student.DoesNotExist:
            return Response({'detail': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

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
                'status': status_val,
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
        ).select_related('session__course').order_by('-verified_at')


class ActiveSessionsForStudentView(generics.ListAPIView):
    """Student sees active sessions for their group."""
    permission_classes = [IsStudent]
    serializer_class = AttendanceSessionSerializer

    def get_queryset(self):
        from django.db.models import Q
        
        student = getattr(self.request.user, 'student_profile', None)
        if not student:
            return AttendanceSession.objects.none()
            
        enrollments = student.enrollments.all()
        course_ids = [e.course_id for e in enrollments]
        group_ids = [e.group_id for e in enrollments if e.group_id]
        
        return AttendanceSession.objects.filter(
            organization=student.organization,
            status=SessionStatus.ACTIVE,
        ).filter(
            Q(course_id__in=course_ids, group__isnull=True) |
            Q(group_id__in=group_ids)
        ).select_related('course', 'group', 'teacher__user').distinct()


class DashboardView(APIView):
    """Admin dashboard summary."""
    permission_classes = [IsOrganizationAdmin]

    def get(self, request):
        from apps.students.models import Student
        from apps.teachers.models import Teacher
        from apps.groups.models import Group

        org = request.user.organization
        today = timezone.now().date()

        return Response({
            'total_students': Student.objects.filter(organization=org, status='ACTIVE').count(),
            'total_teachers': Teacher.objects.filter(organization=org).count(),
            'total_groups': Group.objects.filter(organization=org, status='ACTIVE').count(),
            'active_sessions': AttendanceSession.objects.filter(
                organization=org, status=SessionStatus.ACTIVE
            ).count(),
            'today_attendance': AttendanceRecord.objects.filter(
                session__organization=org,
                verified_at__date=today,
            ).count(),
        })


class AttendanceExportView(APIView):
    """Export attendance records to CSV for a course (or specific group)."""
    permission_classes = [IsAdminOrTeacher]

    def get(self, request):
        import csv
        from django.http import HttpResponse
        from apps.students.models import Student

        course_id = request.query_params.get('course_id')
        group_id = request.query_params.get('group_id')
        
        if not course_id:
            return Response({'detail': 'course_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        sessions = AttendanceSession.objects.filter(
            course_id=course_id,
            organization=request.user.organization,
            status=SessionStatus.CLOSED
        ).order_by('starts_at')
        
        if group_id:
            sessions = sessions.filter(group_id=group_id)

        # Get all students for this course/group
        if group_id:
            students = Student.objects.filter(
                enrollments__group_id=group_id,
                enrollments__course_id=course_id,
                organization=request.user.organization,
                status='ACTIVE'
            ).distinct()
        else:
            students = Student.objects.filter(
                enrollments__course_id=course_id,
                organization=request.user.organization,
                status='ACTIVE'
            ).distinct()

        # Build records map: {student_id: {session_id: status}}
        records = AttendanceRecord.objects.filter(
            session__in=sessions,
            student__in=students
        )
        
        attendance_map = {}
        for r in records:
            if r.student_id not in attendance_map:
                attendance_map[r.student_id] = {}
            attendance_map[r.student_id][r.session_id] = r.status

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="attendance_export_course_{course_id}.csv"'
        
        writer = csv.writer(response)
        
        # Header row
        header = ['Student ID', 'Name', 'Department', 'Level']
        for s in sessions:
            header.append(s.starts_at.strftime('%Y-%m-%d %H:%M'))
        writer.writerow(header)
        
        for student in students:
            row = [
                student.student_id,
                student.user.get_full_name(),
                student.department,
                student.academic_level,
            ]
            for s in sessions:
                # If they have a record, use it, else 'ABSENT'
                status_val = attendance_map.get(student.id, {}).get(s.id, 'ABSENT')
                row.append(status_val)
            writer.writerow(row)

        return response
