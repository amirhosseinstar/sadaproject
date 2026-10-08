from django.urls import path
from rest_framework.routers import DefaultRouter, SimpleRouter

from . import views

# مسیرهای نظرسنجی کلی کلاس باید «قبل» از router اصلی بیایند؛ وگرنه آدرسی مثل
# /api/feedback/class-survey/ به‌جای این‌ها به‌عنوان id یک «انتقاد» تفسیر می‌شود.
survey_router = SimpleRouter()
survey_router.register('class-survey/questions', views.ClassSurveyQuestionViewSet, basename='class-survey-question')
survey_router.register('class-survey/class-questions', views.ClassSpecificQuestionViewSet, basename='class-survey-class-question')
survey_router.register('general-surveys', views.GeneralSurveyViewSet, basename='general-survey')

router = DefaultRouter()
router.register('', views.FeedbackViewSet, basename='feedback')

urlpatterns = [
    path('class-survey/', views.ClassSurveyView.as_view(), name='class-survey'),
    path('class-survey/my-status/', views.ClassSurveyMyStatusView.as_view(), name='class-survey-my-status'),
    path('certificate/<int:enrollment_id>/', views.CertificateDataView.as_view(), name='certificate-data'),
    path('class-survey/my-seminars/', views.MySeminarsSurveyView.as_view(), name='class-survey-my-seminars'),
    path('class-survey/summary/', views.SurveySummaryView.as_view(), name='class-survey-summary'),
    path('class-survey/submit/', views.ClassSurveySubmitView.as_view(), name='class-survey-submit'),
    path('class-survey/results/', views.ClassSurveyResultsView.as_view(), name='class-survey-results'),
    path('class-survey/customized-classes/', views.CustomizedClassesView.as_view(), name='class-survey-customized-classes'),
    path('class-survey/classes/<int:class_id>/', views.ClassSurveyForClassView.as_view(), name='class-survey-for-class'),
    path('class-survey/classes/<int:class_id>/customize/', views.ClassSurveyCustomizeView.as_view(), name='class-survey-customize'),
    *survey_router.urls,
    *router.urls,
]
