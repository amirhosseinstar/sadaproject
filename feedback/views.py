# ===== مسیر این فایل در پروژه: feedback/views.py (کنار manage.py) =====
"""
API انتقادات و پیشنهادات.

  POST    /api/feedback/                -> ثبت یک انتقاد/پیشنهاد (فقط دانش‌پژوهِ واردشده)
  GET     /api/feedback/                -> لیست موارد (مدیر آموزش: همه، مسئول آموزش: فقط شعبه‌ی خودش)
  GET     /api/feedback/<id>/           -> جزئیات یک مورد (همان قاعده)
  DELETE  /api/feedback/<id>/           -> حذف یک مورد (همان قاعده)
  POST    /api/feedback/<id>/reply/     -> ثبت (یا ویرایش) پاسخ + ارسال پیامک به فرستنده (همان قاعده)

نظرسنجی کلی کلاس (یک نظرسنجی برای همه‌ی دانش‌پژوهان):
  GET     /api/feedback/class-survey/                   -> عنوان + سؤال‌ها (هر کاربر واردشده)
  PATCH   /api/feedback/class-survey/                   -> ویرایش عنوان/توضیحات (مدیر/مسئول آموزش)
  POST    /api/feedback/class-survey/questions/         -> افزودن سؤال تستی/تشریحی (همان دو نقش)
  PATCH   /api/feedback/class-survey/questions/<id>/    -> ویرایش سؤال و گزینه‌هایش
  DELETE  /api/feedback/class-survey/questions/<id>/    -> حذف سؤال
  POST    /api/feedback/class-survey/questions/reorder/ -> تغییر ترتیب سؤال‌ها ({"ids": [...]})

شرکت دانش‌پژوه در نظرسنجی (اجباری برای دریافت مدرک هر کلاس):
  GET     /api/feedback/class-survey/my-status/         -> کدام ثبت‌نام‌های خودم نظرسنجی را پر کرده‌اند (دانش‌پژوه)
  POST    /api/feedback/class-survey/submit/            -> ثبت پاسخ‌ها برای یک ثبت‌نام خودم (دانش‌پژوه)
  GET     /api/feedback/class-survey/results/           -> نتایج (مدیر: همه، مسئول آموزش: فقط شعبه‌ی خودش)
"""

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import SimpleRateThrottle

from class_management.models import Enrollment, SiteSettings
from core.permissions import ROLE_MANAGER, ROLE_OFFICER, STAFF_ROLES, IsEducationStaff, staff_role  # noqa: F401

from logs.mixins import AuditedMixin, audit
from logs.recorder import record

from .branches import canonical_branch_name
from .models import ClassSurvey, ClassSurveyQuestion, ClassSurveyResponse, Feedback
from .notifications import send_reply_sms
from .serializers import (
    ClassSurveyQuestionSerializer,
    ClassSurveySerializer,
    ClassSurveySubmitSerializer,
    FeedbackCreateSerializer,
    FeedbackReplySerializer,
    FeedbackSerializer,
)

class FeedbackSubmitThrottle(SimpleRateThrottle):
    """
    محدودیت تعداد ثبت (۱۰ مورد در ساعت) برای هر کاربر، تا نشود پنل را با
    پیام‌های الکی پر کرد. چون ثبت فقط برای کاربر واردشده است، شناسه‌ی
    کاربر ملاک است (نه IP که پشت یک شبکه‌ی مشترک برای چند نفر یکی می‌شود).
    """
    scope = 'feedback_submit'
    rate = '10/hour'

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


def _feedback_summary(action_key, label, target_label, obj, request, response):
    if action_key == 'create':
        kind = request.data.get('kind', '') if hasattr(request.data, 'get') else ''
        return f'ثبت {"انتقاد" if kind == "complaint" else "پیشنهاد"} جدید'
    return f'{label}: {target_label}' if target_label else label


@audit('feedback', 'انتقاد/پیشنهاد', {
    'create': ('feedback_create', 'ثبت انتقاد/پیشنهاد'),
    'reply': ('feedback_reply', 'پاسخ به انتقاد/پیشنهاد'),
    'destroy': ('feedback_delete', 'حذف انتقاد/پیشنهاد'),
}, label_func=lambda f: f'{f.get_kind_display()} شماره {f.pk}', summary_func=_feedback_summary,   # متن پیام هرگز در لاگ همیشگی نمی‌آید
   skip_fields=('member', 'message', 'reply_text'))
class FeedbackViewSet(
    AuditedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Feedback.objects.all()

    def get_permissions(self):
        # برای ثبت، ورود بودن را خودمان داخل create چک می‌کنیم (تا پیام
        # مناسب و کد ۴۰۱ برگردد)؛ همه‌ی کارهای دیگر فقط برای مدیر/مسئول آموزش
        if self.action == 'create':
            return [permissions.AllowAny()]
        return [IsEducationStaff()]

    def get_throttles(self):
        if self.action == 'create':
            return [FeedbackSubmitThrottle()]
        return []

    def get_serializer_class(self):
        if self.action == 'create':
            return FeedbackCreateSerializer
        if self.action == 'reply':
            return FeedbackReplySerializer
        return FeedbackSerializer

    def get_queryset(self):
        qs = Feedback.objects.select_related('member__user', 'member__ban')
        user = self.request.user
        role = staff_role(user)
        if role == ROLE_MANAGER:
            return qs
        if role == ROLE_OFFICER:
            # مسئول آموزش فقط پیام‌های مربوط به شعبه‌ی خودش را می‌بیند. چون
            # get_object (جزئیات/پاسخ/حذف) هم از همین queryset می‌گیرد، مسئول
            # به پیام شعبه‌ی دیگر (حتی با دانستن id) دسترسی ندارد (۴۰۴ می‌گیرد).
            # اگر شعبه‌ی مسئول در سیستم ثبت نشده یا معتبر نباشد، چیزی نمی‌بیند.
            branch = canonical_branch_name(user.employee.branch)
            return qs.filter(branch=branch) if branch else qs.none()
        return qs.none()

    def create(self, request, *args, **kwargs):
        # ۱) بخش باید در سایت فعال باشد (کلید مدیر آموزش)
        if not SiteSettings.load().feedback_enabled:
            return Response({'detail': 'ثبت انتقادات و پیشنهادات در حال حاضر غیرفعال است.'},
                            status=status.HTTP_403_FORBIDDEN)
        # ۲) کاربر باید وارد شده باشد
        if not request.user.is_authenticated:
            return Response({'detail': 'برای ثبت انتقاد یا پیشنهاد ابتدا وارد حساب کاربری خود شوید.'},
                            status=status.HTTP_401_UNAUTHORIZED)
        # ۳) و باید دانش‌پژوه باشد (تا اطلاعات و سوابق آموزشی‌اش برای مدیر قابل‌مشاهده باشد)
        member = getattr(request.user, 'member', None)
        if member is None:
            return Response({'detail': 'ثبت انتقاد و پیشنهاد فقط با حساب دانش‌پژوه امکان‌پذیر است.'},
                            status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # اگر شماره‌ای در فرم وارد نشده، شماره‌ی ثبت‌شده‌ی عضویت جایگزین می‌شود
        # (برای ارسال پیامکِ پاسخ لازم است)
        phone = serializer.validated_data.get('phone') or member.phone or ''
        serializer.save(member=member, phone=phone)
        # عمداً چیزی جز یک پیام تأیید برنمی‌گردانیم
        return Response({'detail': 'پیام شما با موفقیت ثبت شد.'}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        item = self.get_object()
        serializer = FeedbackReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_text = serializer.validated_data['reply_text']
        # پیامک فقط وقتی فرستاده می‌شود که متن پاسخ واقعاً تازه یا عوض‌شده باشد
        # (ویرایش فقط «نام مسئول» نباید یک پیامک تکراری بفرستد)
        text_changed = item.reply_text != new_text

        item.replier_name = serializer.validated_data['replier_name']
        item.reply_text = new_text
        item.replied_at = timezone.now()
        item.status = Feedback.STATUS_ANSWERED
        item.save(update_fields=['replier_name', 'reply_text', 'replied_at', 'status'])

        if text_changed:
            send_reply_sms(item)

        return Response(FeedbackSerializer(item).data)


# ---------------------------------------------------------------------------
# نظرسنجی کلی کلاس
# ---------------------------------------------------------------------------

class ClassSurveyView(APIView):
    """
    خواندن و ویرایش «عنوان/توضیحات» نظرسنجی کلی. چون فقط یک نظرسنجی وجود
    دارد، id در آدرس نیست. خواندن برای هر کاربر واردشده آزاد است (دانش‌پژوه
    هم باید سؤال‌ها را ببیند)؛ ویرایش فقط برای مدیر/مسئول آموزش.
    """

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [IsEducationStaff()]

    def get(self, request):
        return Response(ClassSurveySerializer(ClassSurvey.load()).data)

    def patch(self, request):
        survey = ClassSurvey.load()
        old_title, old_description = survey.title, survey.description
        serializer = ClassSurveySerializer(survey, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        changes = []
        if survey.title != old_title:
            changes.append({'field': 'عنوان نظرسنجی', 'old': old_title, 'new': survey.title})
        if survey.description != old_description:
            changes.append({'field': 'توضیحات نظرسنجی', 'old': old_description, 'new': survey.description})
        if changes:
            record(request, 'survey', 'survey_update', 'ویرایش عنوان/توضیحات نظرسنجی کلی', target_type='نظرسنجی', changes=changes)
        return Response(serializer.data)


@audit('survey', 'سؤال نظرسنجی', {
    'create': ('survey_question_create', 'افزودن سؤال نظرسنجی'),
    'update': ('survey_question_update', 'ویرایش سؤال نظرسنجی'),
    'destroy': ('survey_question_delete', 'حذف سؤال نظرسنجی'),
    'reorder': ('survey_question_reorder', 'تغییر ترتیب سؤال‌های نظرسنجی'),
}, label_func=lambda q: (q.text or '')[:60], skip_fields=('survey',))
class ClassSurveyQuestionViewSet(AuditedMixin, viewsets.ModelViewSet):
    """افزودن/ویرایش/حذف/جابه‌جایی سؤال‌های نظرسنجی کلی (فقط مدیر/مسئول آموزش)."""
    serializer_class = ClassSurveyQuestionSerializer
    permission_classes = [IsEducationStaff]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return ClassSurveyQuestion.objects.filter(survey=ClassSurvey.load())

    def perform_create(self, serializer):
        survey = ClassSurvey.load()
        # سؤال جدید همیشه ته لیست اضافه می‌شود
        last = survey.questions.aggregate(m=Max('order'))['m'] or 0
        serializer.save(survey=survey, order=last + 1)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """ترتیب جدید: {"ids": [3, 1, 2]} - باید دقیقاً همه‌ی سؤال‌های فعلی باشد."""
        ids = request.data.get('ids')
        current = set(self.get_queryset().values_list('id', flat=True))
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) != current:
            return Response({'detail': 'فهرست سؤال‌ها برای تغییر ترتیب معتبر نیست.'},
                            status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for position, question_id in enumerate(ids, start=1):
                ClassSurveyQuestion.objects.filter(pk=question_id).update(order=position)
        return Response(self.get_serializer(self.get_queryset(), many=True).data)


# ---------------------------------------------------------------------------
# شرکت دانش‌پژوه در نظرسنجی + نتایج
# ---------------------------------------------------------------------------

def _member_or_403(request):
    """دانش‌پژوهِ واردشده را برمی‌گرداند؛ اگر دانش‌پژوه نباشد None."""
    return getattr(request.user, 'member', None)


class ClassSurveyMyStatusView(APIView):
    """
    وضعیت شرکت دانش‌پژوه در نظرسنجی. صفحه‌ی مدرک (certificate.html) با این
    می‌فهمد برای کدام کلاس‌ها هنوز باید نظرسنجی پر شود.

    required=False یعنی نظرسنجی الان هیچ سؤالی ندارد؛ در این حالت نباید
    مدرک را قفل کرد (وگرنه دانش‌پژوه برای چیزی که وجود ندارد گیر می‌کند).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        member = _member_or_403(request)
        if member is None:
            return Response({'detail': 'فقط دانش‌پژوه به این بخش دسترسی دارد.'}, status=status.HTTP_403_FORBIDDEN)
        completed = ClassSurveyResponse.objects.filter(enrollment__member=member).values_list('enrollment_id', flat=True)
        return Response({
            'required': ClassSurvey.load().questions.exists(),
            'completed_enrollment_ids': list(completed),
        })


class ClassSurveySubmitView(APIView):
    """ثبت پاسخ نظرسنجی برای «یکی از ثبت‌نام‌های خودِ دانش‌پژوه» (فقط یک‌بار برای هر ثبت‌نام)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        member = _member_or_403(request)
        if member is None:
            return Response({'detail': 'فقط دانش‌پژوه می‌تواند در نظرسنجی شرکت کند.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = ClassSurveySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # ثبت‌نام باید مال همین دانش‌پژوه باشد (نه ثبت‌نام دیگران) - وگرنه ۴۰۴
        enrollment = (
            Enrollment.objects.select_related('class_obj', 'lesson')
            .filter(pk=serializer.validated_data['enrollment_id'], member=member).first()
        )
        if enrollment is None:
            return Response({'detail': 'ثبت‌نام موردنظر پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)

        # نام کلاس و شعبه را همین لحظه ذخیره می‌کنیم (با حذف کلاس هم گزارش‌ها بمانند)
        klass = enrollment.class_obj
        lesson = enrollment.lesson
        raw_branch = (klass.branch if klass else (lesson.branch if lesson else '')) or ''
        already = Response({'detail': 'شما قبلاً در نظرسنجی این کلاس شرکت کرده‌اید.'}, status=status.HTTP_409_CONFLICT)
        if ClassSurveyResponse.objects.filter(enrollment=enrollment).exists():
            return already
        try:
            # داخل transaction.atomic تا اگر دو درخواست هم‌زمان رسید و OneToOne جلوی
            # دومی را گرفت، خطا فقط همین savepoint را بشکند نه کل تراکنش درخواست
            with transaction.atomic():
                ClassSurveyResponse.objects.create(
                    member=member,
                    enrollment=enrollment,
                    class_name=(klass.name if klass else (lesson.name if lesson else '')),
                    branch=canonical_branch_name(raw_branch) or raw_branch,
                    answers=serializer.validated_data['answers'],
                )
        except IntegrityError:
            return already
        record(request, 'survey', 'survey_submit', f'شرکت در نظرسنجی کلاس «{klass.name if klass else (lesson.name if lesson else "")}»',
               target_type='نظرسنجی', target_label=(klass.name if klass else (lesson.name if lesson else '')), branch=raw_branch)
        return Response({'detail': 'از شرکت شما در نظرسنجی سپاسگزاریم.'}, status=status.HTTP_201_CREATED)


class ClassSurveyResultsView(APIView):
    """
    نتایج نظرسنجی برای پنل. مدیر آموزش همه‌ی پاسخ‌ها را می‌بیند؛ مسئول آموزش فقط
    پاسخ‌های کلاس‌های شعبه‌ی خودش (مثل انتقادات و پیشنهادات).

    خروجی: تعداد شرکت‌کنندگان + برای هر سؤالِ «فعلیِ» نظرسنجی:
      - تستی: شمارش هر گزینه (گزینه‌ای که بعداً ویرایش/حذف شده هم با پاسخ‌های قدیمی‌اش می‌ماند)
      - تشریحی: ۵۰ پاسخ متنیِ آخر (به‌همراه کلاس/شعبه/تاریخ)
    """
    permission_classes = [IsEducationStaff]
    MAX_TEXT_ANSWERS = 50

    def get(self, request):
        responses = ClassSurveyResponse.objects.all()
        if staff_role(request.user) == ROLE_OFFICER:
            branch = canonical_branch_name(request.user.employee.branch)
            responses = responses.filter(branch=branch) if branch else responses.none()
        responses = list(responses)   # از جدیدترین به قدیمی‌ترین (ترتیب Meta)

        questions = []
        for q in ClassSurvey.load().questions.all():
            entries = []   # (پاسخ، پاسخ‌دهنده) برای همین سؤال
            for r in responses:
                for a in r.answers:
                    if a.get('question_id') == q.id and (a.get('answer') or '').strip():
                        entries.append((a['answer'], r))
            item = {'id': q.id, 'text': q.text, 'kind': q.kind, 'answered': len(entries)}
            if q.kind == ClassSurveyQuestion.KIND_CHOICE:
                counts = {label: 0 for label in q.options}
                for answer, _ in entries:
                    counts[answer] = counts.get(answer, 0) + 1
                item['options'] = [{'label': label, 'count': count} for label, count in counts.items()]
            else:
                item['answers'] = [
                    {'text': answer, 'class_name': r.class_name, 'branch': r.branch, 'submitted_at': r.submitted_at}
                    for answer, r in entries[:self.MAX_TEXT_ANSWERS]
                ]
            questions.append(item)
        return Response({'participants': len(responses), 'questions': questions})
