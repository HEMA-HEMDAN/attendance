from django.urls import path
from .views import (
    SessionListCreateView, SessionCloseView, SessionReopenView,
    ChallengeRequestView, CheckInView,
    SessionRecordsView, ManualAttendanceOverrideView,
    StudentAttendanceHistoryView, ActiveSessionsForStudentView,
    DashboardView, AttendanceExportView,
)

urlpatterns = [
    # Admin/Dashboard
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('export/', AttendanceExportView.as_view(), name='attendance-export'),

    # Teacher session management
    path('sessions/', SessionListCreateView.as_view(), name='session-list-create'),
    path('sessions/<int:pk>/close/', SessionCloseView.as_view(), name='session-close'),
    path('sessions/<int:pk>/reopen/', SessionReopenView.as_view(), name='session-reopen'),
    path('sessions/<int:session_id>/challenge/', ChallengeRequestView.as_view(), name='challenge-request'),
    path('sessions/<int:session_id>/check-in/', CheckInView.as_view(), name='check-in'),
    path('sessions/<int:pk>/records/', SessionRecordsView.as_view(), name='session-records'),
    path('sessions/<int:pk>/manual-mark/', ManualAttendanceOverrideView.as_view(), name='manual-mark'),
    path('student/history/', StudentAttendanceHistoryView.as_view(), name='student-history'),
    path('student/active-sessions/', ActiveSessionsForStudentView.as_view(), name='active-sessions'),
]
