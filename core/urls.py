# ===== مسیر این فایل در پروژه: core/urls.py (کنار manage.py) =====
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('branches', views.BranchViewSet, basename='branch')
router.register('employees', views.EmployeeViewSet, basename='employee')
router.register('staff', views.StaffViewSet, basename='staff')
router.register('teacher-applicants', views.TeacherApplicantViewSet, basename='teacher-applicant')

urlpatterns = router.urls + [
    path('my-profile/', views.MyProfileView.as_view(), name='my-profile'),
]
