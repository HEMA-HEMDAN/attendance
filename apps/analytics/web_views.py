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


class StaffChangePasswordWebView(View):
    """Session-authenticated password change for academic staff on the Analytics Dashboard."""
    template_name = 'analytics/change_password.html'

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse('web-login'), redirect_field_name='next')
        if request.user.role not in WEB_DASHBOARD_ROLES:
            return HttpResponseForbidden('Students do not have access to analytics staff options.')
        return render(request, self.template_name, {'user': request.user, 'error': None, 'success': None})

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse('web-login'), redirect_field_name='next')
        if request.user.role not in WEB_DASHBOARD_ROLES:
            return HttpResponseForbidden('Students do not have access to analytics staff options.')

        old_password = request.POST.get('old_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not request.user.check_password(old_password):
            return render(request, self.template_name, {
                'user': request.user,
                'error': 'Current password is incorrect.',
                'success': None,
            }, status=400)

        if len(new_password) < 8:
            return render(request, self.template_name, {
                'user': request.user,
                'error': 'New password must be at least 8 characters long.',
                'success': None,
            }, status=400)

        if new_password != confirm_password:
            return render(request, self.template_name, {
                'user': request.user,
                'error': 'New passwords do not match.',
                'success': None,
            }, status=400)

        request.user.set_password(new_password)
        request.user.save()

        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, request.user)

        return render(request, self.template_name, {
            'user': request.user,
            'error': None,
            'success': 'Your password has been changed successfully.',
        })

