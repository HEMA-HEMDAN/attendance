"""
Analytics views — role-scoped analytics APIs.
"""

from django.http import HttpResponse
from django.utils.dateparse import parse_date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.accounts.models import Role
from apps.accounts.permissions import IsDoctor, IsTeachingAssistant, IsOrganizationAdmin, IsSuperadmin, IsStaffOrAdmin
from apps.staff.models import Doctor, TeachingAssistant
from .export_service import AnalyticsExportService
from .services import AnalyticsService


def _analytics_filters(request):
    filters = {
        key: request.query_params.get(key) or None
        for key in (
            'academic_year_id', 'semester_id', 'course_offering_id', 'group_id',
            'session_type', 'search', 'attendance_status', 'sort', 'ordering',
        )
    }
    filters['start_date'] = parse_date(request.query_params.get('date_from', '')) if request.query_params.get('date_from') else None
    filters['end_date'] = parse_date(request.query_params.get('date_to', '')) if request.query_params.get('date_to') else None
    return {key: value for key, value in filters.items() if value not in (None, '')}


def _paginate(rows, request):
    try:
        page = max(int(request.query_params.get('page', 1)), 1)
        page_size = min(max(int(request.query_params.get('page_size', 25)), 1), 100)
    except (TypeError, ValueError):
        page, page_size = 1, 25
    start = (page - 1) * page_size
    return {
        'count': len(rows),
        'page': page,
        'page_size': page_size,
        'results': rows[start:start + page_size],
    }


def _sort_rows(rows, request, allowed):
    sort = request.query_params.get('sort', 'student_name')
    if sort not in allowed:
        sort = 'student_name'
    reverse = request.query_params.get('ordering', 'asc').lower() == 'desc'
    return sorted(rows, key=lambda row: (row.get(sort) is None, row.get(sort)), reverse=reverse)


class AnalyticsStudentListView(APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        filters = _analytics_filters(request)
        rows = AnalyticsService().student_summary_rows(request.user, filters)
        rows = _sort_rows(rows, request, {
            'student_name', 'student_id', 'attendance_rate', 'absent', 'late',
        })
        return Response({
            **_paginate(rows, request),
            'filters': filters,
            'filter_options': AnalyticsService(
                organization=request.user.organization if request.user.role != Role.SUPERADMIN else None
            ).get_filter_options(user=request.user),
        })


class AnalyticsStudentDetailView(APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request, student_id):
        service = AnalyticsService()
        filters = _analytics_filters(request)
        rows = service.student_history_rows(request.user, student_id, filters)
        if not service._eligible_enrollments(request.user, filters, student_id=student_id).exists():
            return Response({'detail': 'Student not found or outside your analytics scope'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'student_id': student_id, **_paginate(rows, request)})


class AnalyticsSessionAttendanceView(APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request, session_id):
        session, rows = AnalyticsService().session_attendance_rows(
            request.user, session_id, _analytics_filters(request)
        )
        if not session:
            return Response({'detail': 'Session not found or outside your analytics scope'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'session': {
                'id': session.id,
                'date': session.occurrence.scheduled_date,
                'course': session.occurrence.course_offering.course.code,
                'course_name': session.occurrence.course_offering.course.name,
                'group': session.occurrence.group.name if session.occurrence.group else 'All Groups',
                'session_type': session.occurrence.session_type,
                'starts_at': session.starts_at,
                'expires_at': session.expires_at,
                'status': session.status,
            },
            **_paginate(rows, request),
        })


class AnalyticsExportView(APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request, export_type):
        service = AnalyticsService()
        filters = _analytics_filters(request)
        if export_type == 'course':
            content = AnalyticsExportService.course_summary(
                service.student_summary_rows(request.user, filters)
            )
            filename = 'attendance-summary.xlsx'
        elif export_type == 'session':
            session_id = request.query_params.get('session_id')
            if not session_id:
                return Response({'detail': 'session_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            session, rows = service.session_attendance_rows(request.user, session_id, filters)
            if not session:
                return Response({'detail': 'Session not found or outside your analytics scope'}, status=status.HTTP_404_NOT_FOUND)
            content = AnalyticsExportService.session_details(rows)
            filename = f'session-{session.id}-attendance.xlsx'
        elif export_type == 'student':
            student_id = request.query_params.get('student_id')
            if not student_id:
                return Response({'detail': 'student_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            rows = service.student_history_rows(request.user, student_id, filters)
            if not service._eligible_enrollments(request.user, filters, student_id=student_id).exists():
                return Response({'detail': 'Student not found or outside your analytics scope'}, status=status.HTTP_404_NOT_FOUND)
            content = AnalyticsExportService.student_history(rows)
            filename = f'student-{student_id}-attendance.xlsx'
        else:
            return Response({'detail': 'Unknown export type'}, status=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class DoctorAnalyticsView(APIView):
    """Doctor Analytics: owned course offerings, all sections, attendance, trends."""
    permission_classes = [IsDoctor]

    def get(self, request):
        doc = Doctor.objects.filter(user=request.user, organization=request.user.organization).first()
        if not doc:
            return Response({'detail': 'Doctor profile not found'}, status=status.HTTP_404_NOT_FOUND)

        svc = AnalyticsService(organization=request.user.organization)

        year_id = request.query_params.get('academic_year_id')
        sem_id = request.query_params.get('semester_id')
        offering_id = request.query_params.get('course_offering_id')
        group_id = request.query_params.get('group_id')

        metrics = svc.calculate_metrics(
            academic_year_id=year_id,
            semester_id=sem_id,
            course_offering_id=offering_id,
            group_id=group_id,
            doctor_id=doc.id,
        )

        offerings = doc.course_offerings.filter(status='ACTIVE').select_related('course')
        offering_summary = []
        for o in offerings:
            m = svc.calculate_metrics(course_offering_id=o.id, doctor_id=doc.id)
            offering_summary.append({
                'course_offering_id': o.id,
                'course_code': o.course.code,
                'course_name': o.course.name,
                'metrics': m,
            })

        return Response({
            'overall_metrics': metrics,
            'course_offerings': offering_summary,
        })


class TeachingAssistantAnalyticsView(APIView):
    """TA Analytics: assigned groups, related courses, attendance."""
    permission_classes = [IsTeachingAssistant]

    def get(self, request):
        ta = TeachingAssistant.objects.filter(user=request.user, organization=request.user.organization).first()
        if not ta:
            return Response({'detail': 'Teaching Assistant profile not found'}, status=status.HTTP_404_NOT_FOUND)

        svc = AnalyticsService(organization=request.user.organization)

        year_id = request.query_params.get('academic_year_id')
        sem_id = request.query_params.get('semester_id')
        group_id = request.query_params.get('group_id')

        metrics = svc.calculate_metrics(
            academic_year_id=year_id,
            semester_id=sem_id,
            group_id=group_id,
            ta_id=ta.id,
        )

        assigned_groups = ta.assigned_groups.filter(status='ACTIVE').select_related('course_offering__course')
        group_summary = []
        for g in assigned_groups:
            m = svc.calculate_metrics(group_id=g.id, ta_id=ta.id)
            group_summary.append({
                'group_id': g.id,
                'group_name': g.name,
                'course_code': g.course_offering.course.code,
                'metrics': m,
            })

        return Response({
            'overall_metrics': metrics,
            'assigned_groups': group_summary,
        })


class OrganizationAdminAnalyticsView(APIView):
    """Organization Admin Analytics: organization-wide metrics."""
    permission_classes = [IsOrganizationAdmin]

    def get(self, request):
        svc = AnalyticsService(organization=request.user.organization)

        year_id = request.query_params.get('academic_year_id')
        sem_id = request.query_params.get('semester_id')
        offering_id = request.query_params.get('course_offering_id')
        group_id = request.query_params.get('group_id')
        sess_type = request.query_params.get('session_type')

        metrics = svc.calculate_metrics(
            academic_year_id=year_id,
            semester_id=sem_id,
            course_offering_id=offering_id,
            group_id=group_id,
            session_type=sess_type,
        )

        from apps.students.models import Student
        from apps.staff.models import Doctor, TeachingAssistant
        from apps.groups.models import Group

        org = request.user.organization
        counts = {
            'total_students': Student.objects.filter(organization=org, status='ACTIVE').count(),
            'total_doctors': Doctor.objects.filter(organization=org).count(),
            'total_tas': TeachingAssistant.objects.filter(organization=org).count(),
            'total_groups': Group.objects.filter(course_offering__course__organization=org, status='ACTIVE').count(),
        }

        return Response({
            'organization_counts': counts,
            'metrics': metrics,
        })


class SuperadminAnalyticsView(APIView):
    """Superadmin Analytics: platform-wide aggregates."""
    permission_classes = [IsSuperadmin]

    def get(self, request):
        svc = AnalyticsService(organization=None)
        metrics = svc.calculate_metrics()

        from apps.organizations.models import Organization
        org_list = []
        for org in Organization.objects.all():
            org_svc = AnalyticsService(organization=org)
            org_list.append({
                'organization_id': org.id,
                'organization_name': org.name,
                'metrics': org_svc.calculate_metrics(),
            })

        return Response({
            'platform_metrics': metrics,
            'organizations': org_list,
        })


from django.shortcuts import render
from rest_framework.renderers import TemplateHTMLRenderer, JSONRenderer
from rest_framework.permissions import IsAuthenticated


def _query_value(request, key):
    if hasattr(request, 'query_params'):
        return request.query_params.get(key)
    return request.GET.get(key)


def build_analytics_dashboard_context(request):
    """Role-scoped dashboard context used by both JWT API and Django session web views."""
    user = request.user
    svc = AnalyticsService(organization=user.organization if user.role != Role.SUPERADMIN else None)

    year_id = _query_value(request, 'academic_year_id')
    sem_id = _query_value(request, 'semester_id')
    offering_id = _query_value(request, 'course_offering_id')
    group_id = _query_value(request, 'group_id')
    sess_type = _query_value(request, 'session_type')

    doc_id = None
    ta_id = None

    role_details = []

    if user.role == Role.DOCTOR:
        doc = Doctor.objects.filter(user=user, organization=user.organization).first()
        if doc:
            doc_id = doc.id
            offerings = doc.course_offerings.filter(status='ACTIVE').select_related('course')
            for o in offerings:
                m = svc.calculate_metrics(course_offering_id=o.id, doctor_id=doc.id)
                role_details.append({
                    'name': f"{o.course.code} — {o.course.name}",
                    'metrics': m,
                })
    elif user.role == Role.TEACHING_ASSISTANT:
        ta = TeachingAssistant.objects.filter(user=user, organization=user.organization).first()
        if ta:
            ta_id = ta.id
            assigned_groups = ta.assigned_groups.filter(status='ACTIVE').select_related('course_offering__course')
            for g in assigned_groups:
                m = svc.calculate_metrics(group_id=g.id, ta_id=ta.id)
                role_details.append({
                    'name': f"{g.course_offering.course.code} ({g.name})",
                    'metrics': m,
                })
    elif user.role in [Role.ADMIN, Role.SUPERADMIN]:
        from apps.courses.models import CourseOffering
        offerings = CourseOffering.objects.filter(
            course__organization=user.organization if user.role != Role.SUPERADMIN else None,
            status='ACTIVE'
        ).select_related('course') if user.organization or user.role == Role.SUPERADMIN else []
        for o in offerings:
            m = svc.calculate_metrics(course_offering_id=o.id)
            role_details.append({
                'name': f"{o.course.code} — {o.course.name}",
                'metrics': m,
            })

    metrics = svc.calculate_metrics(
        academic_year_id=year_id,
        semester_id=sem_id,
        course_offering_id=offering_id,
        group_id=group_id,
        session_type=sess_type,
        doctor_id=doc_id,
        ta_id=ta_id,
    )

    filter_options = svc.get_filter_options(user=user)
    student_rows = svc.student_summary_rows(user, {
        'academic_year_id': year_id,
        'semester_id': sem_id,
        'course_offering_id': offering_id,
        'group_id': group_id,
        'session_type': sess_type,
        'start_date': _query_value(request, 'date_from'),
        'end_date': _query_value(request, 'date_to'),
        'search': _query_value(request, 'search'),
    })
    session_rows = svc.session_list_rows(user, {
        'academic_year_id': year_id,
        'semester_id': sem_id,
        'course_offering_id': offering_id,
        'group_id': group_id,
        'session_type': sess_type,
        'start_date': _query_value(request, 'date_from'),
        'end_date': _query_value(request, 'date_to'),
    })

    user_dict = {
        'id': user.id,
        'email': user.email,
        'full_name': user.get_full_name(),
        'role': user.role,
        'get_full_name': user.get_full_name(),
    }

    return {
        'user': user_dict,
        'metrics': metrics,
        'role_details': role_details,
        'filter_options': filter_options,
        'student_rows': student_rows[:100],
        'session_rows': session_rows[:100],
        'student_export_query': request.GET.urlencode() if hasattr(request, 'GET') else '',
    }


class AnalyticsDashboardWebView(APIView):
    """
    JWT/API dashboard for DOCTOR, TEACHING_ASSISTANT, ADMIN, SUPERADMIN.
    Browser session access is served by AnalyticsDashboardPage at /analytics/dashboard/.
    """
    permission_classes = [IsAuthenticated]
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'analytics/dashboard.html'

    def get(self, request):
        context = build_analytics_dashboard_context(request)

        if request.accepted_renderer.format == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', ''):
            return render(request, self.template_name, context)

        return Response(context)

