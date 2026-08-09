from django.urls import path
from .views import CourseViewSet, CourseDetailView

urlpatterns = [
    path('', CourseViewSet.as_view(), name='course-list'),
    path('<int:pk>/', CourseDetailView.as_view(), name='course-detail'),
]
