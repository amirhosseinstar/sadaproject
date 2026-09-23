from django.urls import path

from . import views

urlpatterns = [
    path('export/', views.LogExportView.as_view(), name='log-export'),
    path('', views.LogListView.as_view(), name='log-list'),
]
