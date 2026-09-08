from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('terms', views.AcademicTermViewSet, basename='academic-term')

urlpatterns = [
    path('', views.PublicCalendarView.as_view(), name='calendar-public'),
    path('years/', views.CalendarYearsView.as_view(), name='calendar-years'),
    path('pdf/', views.CalendarPdfView.as_view(), name='calendar-pdf'),
    path('', include(router.urls)),
]
