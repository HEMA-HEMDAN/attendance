from django.urls import path
from .views import (
    StudentListCreateView, StudentDetailView,
    CSVImportValidateView, CSVImportExecuteView,
    MyProfileView, UpdatePersonalEmailView,
    StudentEnrollmentListCreateView, BulkStudentEnrollmentView,
)

urlpatterns = [
    path('', StudentListCreateView.as_view(), name='student-list'),
    path('<int:pk>/', StudentDetailView.as_view(), name='student-detail'),
    path('<int:pk>/bulk-enroll/', BulkStudentEnrollmentView.as_view(), name='student-bulk-enroll'),
    path('enrollments/', StudentEnrollmentListCreateView.as_view(), name='student-enrollment-list'),
    path('import/validate/', CSVImportValidateView.as_view(), name='student-import-validate'),
    path('import/execute/', CSVImportExecuteView.as_view(), name='student-import-execute'),
    path('me/', MyProfileView.as_view(), name='student-me'),
    path('me/personal-email/', UpdatePersonalEmailView.as_view(), name='student-personal-email'),
]
