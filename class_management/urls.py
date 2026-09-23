from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('departments', views.DepartmentViewSet, basename='department')
router.register('lessons', views.LessonViewSet, basename='lesson')
router.register('questions', views.QuestionViewSet, basename='question')
router.register('branch-departments', views.BranchDepartmentViewSet, basename='branch-department')
router.register('classes', views.ClassViewSet, basename='class')
router.register('enrollments', views.EnrollmentViewSet, basename='enrollment')

urlpatterns = [
    path('site-settings/', views.SiteSettingsView.as_view(), name='site-settings'),
    path('teacher-permissions/', views.TeacherLessonPermissionView.as_view(), name='teacher-permissions'),
    path('', include(router.urls)),
]
