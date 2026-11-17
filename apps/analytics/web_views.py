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

        service = AnalyticsService()
        session, all_rows = service.session_attendance_rows(request.user, session_id, {})
        if not session:
            return HttpResponseForbidden('Session is outside your analytics scope.')

        total_count = len(all_rows)
        present_count = sum(1 for r in all_rows if r['status'] == 'PRESENT')
        late_count = sum(1 for r in all_rows if r['status'] == 'LATE')
        absent_count = sum(1 for r in all_rows if r['status'] == 'ABSENT')
        excused_count = sum(1 for r in all_rows if r['status'] == 'EXCUSED')
        cheating_count = sum(1 for r in all_rows if r['status'] == 'CHEATING')
        attended_count = present_count + late_count + excused_count
        attendance_rate = round((attended_count / total_count * 100), 1) if total_count > 0 else 0.0

        available_groups = sorted(list({r['group'] for r in all_rows if r.get('group') and r['group'] != 'All Groups'}))

        active_filters = {
            'attendance_status': request.GET.get('attendance_status', ''),
            'search': request.GET.get('search', ''),
            'group': request.GET.get('group', ''),
            'distance_filter': request.GET.get('distance_filter', ''),
            'sort': request.GET.get('sort', 'student_name'),
            'ordering': request.GET.get('ordering', 'asc'),
        }

        # Apply server-side filters if query params exist
        filters_for_service = {k: v for k, v in active_filters.items() if v}
        _, filtered_rows = service.session_attendance_rows(request.user, session_id, filters_for_service)

        export_params = request.GET.copy()
        export_params['session_id'] = session.id
        export_url = f"/api/v1/analytics/export/session/?{export_params.urlencode()}"

        import json
        return render(request, 'analytics/session_attendance.html', {
            'user': request.user,
            'session': session,
            'rows': filtered_rows,
            'all_rows_json': json.dumps(all_rows),
            'metrics': {
                'total': total_count,
                'present': present_count,
                'late': late_count,
                'absent': absent_count,
                'excused': excused_count,
                'cheating': cheating_count,
                'attendance_rate': attendance_rate,
            },
            'available_groups': available_groups,
            'filters': active_filters,
            'export_url': export_url,
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

