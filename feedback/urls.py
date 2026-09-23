from django.urls import path
from rest_framework.routers import DefaultRouter, SimpleRouter

from . import views

# مسیرهای نظرسنجی کلی کلاس باید «قبل» از router اصلی بیایند؛ وگرنه آدرسی مثل
# /api/feedback/class-survey/ به‌جای این‌ها به‌عنوان id یک «انتقاد» تفسیر می‌شود.
survey_router = SimpleRouter()
survey_router.register('class-survey/questions', views.ClassSurveyQuestionViewSet, basename='class-survey-question')

router = DefaultRouter()
router.register('', views.FeedbackViewSet, basename='feedback')

urlpatterns = [
    path('class-survey/', views.ClassSurveyView.as_view(), name='class-survey'),
    path('class-survey/my-status/', views.ClassSurveyMyStatusView.as_view(), name='class-survey-my-status'),
    path('class-survey/submit/', views.ClassSurveySubmitView.as_view(), name='class-survey-submit'),
    path('class-survey/results/', views.ClassSurveyResultsView.as_view(), name='class-survey-results'),
    *survey_router.urls,
    *router.urls,
]
