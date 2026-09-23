from django.urls import path
from .views import (
    AcademicYearListCreateView, SemesterListCreateView,
    CourseViewSet, CourseDetailView, CourseOfferingListCreateView,
    ScheduleListCreateView, ScheduleExceptionListCreateView,
)

urlpatterns = [
    path('academic-years/', AcademicYearListCreateView.as_view(), name='academic-year-list'),
    path('semesters/', SemesterListCreateView.as_view(), name='semester-list'),
    path('offerings/', CourseOfferingListCreateView.as_view(), name='course-offering-list'),
    path('schedules/', ScheduleListCreateView.as_view(), name='schedule-list'),
    path('exceptions/', ScheduleExceptionListCreateView.as_view(), name='schedule-exception-list'),
    path('', CourseViewSet.as_view(), name='course-list'),
    path('<int:pk>/', CourseDetailView.as_view(), name='course-detail'),
]
