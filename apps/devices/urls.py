from django.urls import path
from .views import (
    DeviceRegisterView, DeviceListView, DeviceRevokeView,
    AdminDeviceListView, AdminDeviceRevokeView,
)

urlpatterns = [
    path('register/', DeviceRegisterView.as_view(), name='device-register'),
    path('my/', DeviceListView.as_view(), name='device-list'),
    path('my/<int:pk>/revoke/', DeviceRevokeView.as_view(), name='device-revoke'),
    path('admin/', AdminDeviceListView.as_view(), name='admin-device-list'),
    path('admin/<int:pk>/revoke/', AdminDeviceRevokeView.as_view(), name='admin-device-revoke'),
]
