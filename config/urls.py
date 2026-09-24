from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.accounts.web_views import WebLoginView, WebLogoutView
from apps.analytics.web_views import AnalyticsDashboardPage

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', WebLoginView.as_view(), name='web-login'),
    path('logout/', WebLogoutView.as_view(), name='web-logout'),
    path('analytics/dashboard/', AnalyticsDashboardPage.as_view(), name='analytics-dashboard-web'),
    path('api/v1/', include('config.api_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
