"""Django session-authenticated analytics dashboard page."""

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from apps.accounts.models import Role
from apps.accounts.web_views import WEB_DASHBOARD_ROLES
from .views import build_analytics_dashboard_context


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
