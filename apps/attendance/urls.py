from django.urls import path
from .views import (
    TodayWorkView, OpenOccurrenceSessionView, SessionCloseView, SessionDeleteView,
    ChallengeRequestView, CheckInView, SessionRecordsView, ManualAttendanceOverrideView,
    StudentAttendanceHistoryView, SessionListCreateView,
)

urlpatterns = [
    path('today/', TodayWorkView.as_view(), name='attendance-today'),
    path('occurrences/<int:occurrence_id>/open/', OpenOccurrenceSessionView.as_view(), name='occurrence-open'),
    path('sessions/', SessionListCreateView.as_view(), name='session-list'),
    path('sessions/<int:pk>/close/', SessionCloseView.as_view(), name='session-close'),
    path('sessions/<int:pk>/', SessionDeleteView.as_view(), name='session-delete'),
    path('sessions/<int:session_id>/challenge/', ChallengeRequestView.as_view(), name='session-challenge'),
    path('sessions/<int:session_id>/checkin/', CheckInView.as_view(), name='session-checkin'),
    path('sessions/<int:pk>/records/', SessionRecordsView.as_view(), name='session-records'),
    path('sessions/<int:pk>/override/', ManualAttendanceOverrideView.as_view(), name='session-override'),
    path('history/', StudentAttendanceHistoryView.as_view(), name='attendance-history'),
]
