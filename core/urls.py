from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('branches', views.BranchViewSet, basename='branch')
router.register('employees', views.EmployeeViewSet, basename='employee')
router.register('staff', views.StaffViewSet, basename='staff')
router.register('teacher-applicants', views.TeacherApplicantViewSet, basename='teacher-applicant')

urlpatterns = router.urls
