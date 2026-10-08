# ===== مسیر این فایل در پروژه: class_management/urls.py (کنار manage.py) =====
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
router.register('announcements', views.AnnouncementViewSet, basename='announcement')
router.register('slides', views.SlideViewSet, basename='slide')
router.register('seminars', views.SeminarViewSet, basename='seminar')

urlpatterns = [
    path('site-settings/', views.SiteSettingsView.as_view(), name='site-settings'),
    path('teacher-permissions/', views.TeacherLessonPermissionView.as_view(), name='teacher-permissions'),
    path('slideshow/public/', views.PublicSlidesView.as_view(), name='slideshow-public'),
    path('slideshow/settings/', views.SlideSettingsView.as_view(), name='slideshow-settings'),
    path('announcements-public/', views.PublicAnnouncementsView.as_view(), name='announcements-public'),
    path('rules/', views.RulesView.as_view(), name='rules'),
    path('my-lessons/', views.TeacherMyLessonsView.as_view(), name='teacher-my-lessons'),
    path('', include(router.urls)),
]
