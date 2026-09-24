"""
Browser (Django session) authentication for the analytics web dashboard.

JWT login at /api/v1/auth/login/ is unchanged and remains the mobile/API path.
"""

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from apps.accounts.models import Role

WEB_DASHBOARD_ROLES = {
    Role.DOCTOR,
    Role.TEACHING_ASSISTANT,
    Role.ADMIN,
    Role.SUPERADMIN,
}

DEFAULT_NEXT = '/analytics/dashboard/'


def safe_next_url(request, fallback=DEFAULT_NEXT):
    next_url = request.POST.get('next') or request.GET.get('next') or fallback
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return fallback


class WebLoginView(View):
    template_name = 'accounts/login.html'

    def get(self, request):
        if request.user.is_authenticated and request.user.role in WEB_DASHBOARD_ROLES:
            return redirect(safe_next_url(request))
        return render(request, self.template_name, {
            'next': request.GET.get('next', DEFAULT_NEXT),
            'error': None,
        })

    def post(self, request):
        email = (request.POST.get('email') or '').strip().lower()
        password = request.POST.get('password') or ''
        next_url = safe_next_url(request)

        if not email or not password:
            return render(request, self.template_name, {
                'next': next_url,
                'error': 'Please enter your email and password.',
                'email': email,
            }, status=400)

        user = authenticate(request, username=email, password=password)
        if user is None:
            return render(request, self.template_name, {
                'next': next_url,
                'error': 'Invalid email or password.',
                'email': email,
            }, status=400)

        if user.role not in WEB_DASHBOARD_ROLES:
            return render(request, self.template_name, {
                'next': next_url,
                'error': 'This dashboard is for academic staff only.',
                'email': email,
            }, status=403)

        login(request, user)
        return redirect(next_url)


class WebLogoutView(View):
    def get(self, request):
        return self._logout(request)

    def post(self, request):
        return self._logout(request)

    def _logout(self, request):
        logout(request)
        return redirect('web-login')
