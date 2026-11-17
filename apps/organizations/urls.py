from django.urls import path
from .views import OrganizationDetailView, OrganizationListCreateView

urlpatterns = [
    path('', OrganizationListCreateView.as_view(), name='organization-list-create'),
    path('me/', OrganizationDetailView.as_view(), name='organization-detail'),
]
