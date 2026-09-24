"""Django session-authenticated analytics dashboard page."""

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from apps.accounts.models import Role
from apps.accounts.web_views import WEB_DASHBOARD_ROLES
from .views import build_analytics_dashboard_context
from .services import AnalyticsService
from apps.students.models import Student


class AnalyticsDashboardPage(View):
    """Human-facing analytics page authenticated via Django session cookies."""

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=reverse('web-login'),
                redirect_field_name='next',
            )
        if request.user.role not in WEB_DASHBOARD_ROLES:
            return HttpResponseForbidden('Students do not have access to the analytics dashboard.')

        context = build_analytics_dashboard_context(request)
        return render(request, 'analytics/dashboard.html', context)


class AnalyticsStudentDetailPage(View):
    """Browser drill-down for one student inside the authenticated scope."""

    def get(self, request, student_id):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse('web-login'), redirect_field_name='next')
        if request.user.role not in WEB_DASHBOARD_ROLES:
            return HttpResponseForbidden('Students do not have access to analytics.')
        service = AnalyticsService()
        enrollments = service._eligible_enrollments(request.user, student_id=student_id)
        student = Student.objects.filter(pk=student_id).select_related('user').first()
        if not student or not enrollments.exists():
            return HttpResponseForbidden('Student is outside your analytics scope.')
        rows = service.student_history_rows(request.user, student_id, {})
        return render(request, 'analytics/student_detail.html', {
            'user': request.user,
            'student': student,
            'rows': rows,
            'export_url': f"/api/v1/analytics/export/student/?student_id={student.id}",
        })


class AnalyticsSessionAttendancePage(View):
    """Browser drill-down for a scoped session attendance sheet."""

    def get(self, request, session_id):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse('web-login'), redirect_field_name='next')
        if request.user.role not in WEB_DASHBOARD_ROLES:
            return HttpResponseForbidden('Students do not have access to analytics.')
        session, rows = AnalyticsService().session_attendance_rows(request.user, session_id, {})
        if not session:
            return HttpResponseForbidden('Session is outside your analytics scope.')
        return render(request, 'analytics/session_attendance.html', {
            'user': request.user,
            'session': session,
            'rows': rows,
            'export_url': f"/api/v1/analytics/export/session/?session_id={session.id}",
        })
