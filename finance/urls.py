from django.urls import path

from . import views

urlpatterns = [
    path('teacher-payments/classes/', views.TeacherPaymentClassesView.as_view(), name='teacher-payment-classes'),
    path('teacher-payments/history/', views.TeacherPaymentHistoryView.as_view(), name='teacher-payment-history'),
    path('teacher-payments/', views.TeacherPaymentCreateView.as_view(), name='teacher-payment-create'),
    path('teacher-payments/<int:pk>/', views.TeacherPaymentDetailView.as_view(), name='teacher-payment-detail'),
    path('teacher-payments/<int:pk>/cancel/', views.TeacherPaymentCancelView.as_view(), name='teacher-payment-cancel'),
]
