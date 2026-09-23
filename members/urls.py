from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('members', views.MemberViewSet, basename='member')

urlpatterns = [
    path('auth/csrf/', views.CsrfView.as_view(), name='auth-csrf'),
    path('auth/login/', views.LoginView.as_view(), name='auth-login'),
    path('auth/logout/', views.LogoutView.as_view(), name='auth-logout'),
    path('auth/me/', views.MeView.as_view(), name='auth-me'),
    path('auth/forgot-password/request/', views.ForgotPasswordRequestView.as_view(), name='auth-forgot-password-request'),
    path('auth/forgot-password/confirm/', views.ForgotPasswordConfirmView.as_view(), name='auth-forgot-password-confirm'),
    path('auth/teacher-forgot-password/request/', views.TeacherForgotPasswordRequestView.as_view(), name='auth-teacher-forgot-password-request'),
    path('auth/teacher-forgot-password/confirm/', views.TeacherForgotPasswordConfirmView.as_view(), name='auth-teacher-forgot-password-confirm'),
    path('auth/otp-login/request/', views.OTPLoginRequestView.as_view(), name='auth-otp-login-request'),
    path('auth/otp-login/verify/', views.OTPLoginVerifyView.as_view(), name='auth-otp-login-verify'),
    path('members/verify/', views.MemberVerifyView.as_view(), name='member-verify'),
] + router.urls
