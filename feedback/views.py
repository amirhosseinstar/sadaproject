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

from class_management.models import Class, Enrollment, Seminar, SeminarEnrollment, SiteSettings
from core.permissions import (  # noqa: F401
    ROLE_MANAGER, ROLE_OFFICER, STAFF_ROLES, IsEducationManager, IsEducationStaff,
    officer_branch_name, same_branch, staff_role,
)

from logs.mixins import AuditedMixin, audit
from logs.recorder import record

from .branches import canonical_branch_name
from .models import (
    ClassSurvey, ClassSurveyQuestion, ClassSurveyResponse, Feedback, GeneralSurvey,
    GeneralSurveyQuestion, GeneralSurveyResponse, effective_questions,
)
from .notifications import send_reply_sms
from .serializers import (
    ClassSpecificQuestionSerializer,
    ClassSurveyQuestionSerializer,
    ClassSurveySerializer,
    ClassSurveySubmitSerializer,
    FeedbackCreateSerializer,
    FeedbackReplySerializer,
    FeedbackSerializer,
    GeneralSurveySerializer,
    GeneralSurveySubmitSerializer,
    snapshot_answers,
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
        template_has_questions = ClassSurvey.load().questions.exists()
        # کلاس‌هایی که سؤال اختصاصی دارند (برای آن‌ها نظرسنجی همیشه لازم است)
        custom_class_ids = set(ClassSurveyQuestion.objects.filter(class_obj__isnull=False).values_list('class_obj_id', flat=True))
        not_required = []
        for enrollment_id, class_id in Enrollment.objects.filter(member=member).values_list('id', 'class_obj_id'):
            if not template_has_questions and class_id not in custom_class_ids:
                not_required.append(enrollment_id)   # نه قالب سؤال دارد نه این کلاس => مدرک قفل نمی‌شود
        return Response({
            'required': template_has_questions or bool(custom_class_ids),
            'completed_enrollment_ids': list(completed),
            'not_required_enrollment_ids': not_required,
        })


class CertificateDataView(APIView):
    """
    اطلاعات مدرک یک ثبت‌نام؛ «قفل سمت سرور» نظرسنجی.
    فقط وقتی داده برمی‌گردد که: ثبت‌نام مال خودِ دانش‌پژوه باشد، نمره‌ی قبولی (بالای ۷۴) داشته باشد،
    و نظرسنجی همان کلاس را پر کرده باشد (یا آن کلاس اصلاً نظرسنجی نداشته باشد).
    در غیر این صورت ۴۰۳ با survey_required=true؛ صفحه‌ی مدرک بدون این پاسخ چیزی چاپ نمی‌کند.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, enrollment_id):
        member = _member_or_403(request)
        if member is None:
            return Response({'detail': 'فقط دانش‌پژوه به این بخش دسترسی دارد.'}, status=status.HTTP_403_FORBIDDEN)
        enrollment = Enrollment.objects.select_related('class_obj', 'class_obj__term').filter(pk=enrollment_id, member=member).first()
        if enrollment is None or enrollment.class_obj is None:
            return Response({'detail': 'ثبت‌نام پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        if enrollment.absent or enrollment.score is None or enrollment.score <= 74:
            return Response({'detail': 'شرایط دریافت مدرک برای این کلاس برقرار نیست.'}, status=status.HTTP_403_FORBIDDEN)
        klass = enrollment.class_obj
        # نظرسنجی لازم است مگر اینکه نه قالب سؤال داشته باشد نه خود کلاس
        needs_survey = ClassSurvey.load().questions.exists() or klass.survey_questions.exists()
        if needs_survey and not ClassSurveyResponse.objects.filter(enrollment=enrollment).exists():
            return Response({'detail': 'برای دریافت مدرک ابتدا نظرسنجی این کلاس را تکمیل کنید.', 'survey_required': True},
                            status=status.HTTP_403_FORBIDDEN)
        term = klass.term
        return Response({
            'enrollment_id': enrollment.id,
            'course': klass.name,
            'branch': klass.branch,
            'class_type': klass.class_type,
            'hours': klass.duration_hours_raw,
            'score': enrollment.score,
            'term_year': getattr(term, 'year', None),
            'term_order': getattr(term, 'order', None),
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

        # نظرسنجی سمینار/کارگاه (سؤال‌ها همان قالب کلی)
        if serializer.validated_data.get('seminar_enrollment_id'):
            return self._submit_seminar(request, member, serializer.validated_data)

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


    def _submit_seminar(self, request, member, data):
        sem_enrollment = SeminarEnrollment.objects.select_related('seminar').filter(
            pk=data['seminar_enrollment_id'], member=member).first()
        if sem_enrollment is None or sem_enrollment.seminar is None:
            return Response({'detail': 'ثبت‌نام موردنظر پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        seminar = sem_enrollment.seminar
        already = Response({'detail': 'شما قبلاً در نظرسنجی این سمینار شرکت کرده‌اید.'}, status=status.HTTP_409_CONFLICT)
        if ClassSurveyResponse.objects.filter(seminar_enrollment=sem_enrollment).exists():
            return already
        try:
            with transaction.atomic():
                ClassSurveyResponse.objects.create(
                    member=member, seminar_enrollment=sem_enrollment, class_name=seminar.name,
                    branch=canonical_branch_name(seminar.branch or '') or (seminar.branch or ''),
                    answers=data['answers'],
                )
        except IntegrityError:
            return already
        record(request, 'survey', 'survey_submit', f'شرکت در نظرسنجی سمینار «{seminar.name}»',
               target_type='نظرسنجی', target_label=seminar.name, branch=seminar.branch)
        return Response({'detail': 'از شرکت شما در نظرسنجی سپاسگزاریم.'}, status=status.HTTP_201_CREATED)


class MySeminarsSurveyView(APIView):
    """سمینارها/کارگاه‌های ثبت‌نام‌شده‌ی دانش‌پژوه و اینکه نظرسنجی‌شان پر شده یا نه."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        member = _member_or_403(request)
        if member is None:
            return Response({'detail': 'فقط دانش‌پژوه به این بخش دسترسی دارد.'}, status=status.HTTP_403_FORBIDDEN)
        has_questions = ClassSurvey.load().questions.exists()
        done = set(ClassSurveyResponse.objects.filter(seminar_enrollment__member=member).values_list('seminar_enrollment_id', flat=True))
        items = []
        for e in SeminarEnrollment.objects.filter(member=member, seminar__isnull=False).select_related('seminar', 'seminar__term'):
            items.append({
                'id': e.id, 'seminar_name': e.seminar.name, 'branch': e.seminar.branch,
                'class_type': e.seminar.class_type,
                'term_order': getattr(e.seminar.term, 'order', None), 'term_year': getattr(e.seminar.term, 'year', None),
                'completed': e.id in done, 'required': has_questions,
            })
        return Response(items)


STANDARD_VOTES = ['خیلی خوب', 'خوب', 'متوسط', 'بد', 'خیلی بد']


class SurveySummaryView(APIView):
    """
    گزارش کلی نظرسنجی‌های یک شعبه (کلاسی + سمینار + کلی): تعداد نظرسنجی‌های برگزارشده،
    تعداد رأی‌دهندگان و شمارش رأی‌های استاندارد «خیلی خوب … خیلی بد» در سؤال‌های تستی.
    مدیر آموزش: ?branch= ؛ مسئول آموزش: همیشه فقط شعبه‌ی خودش.
    """
    permission_classes = [IsEducationStaff]

    def get(self, request):
        own = officer_branch_name(request.user)
        wanted = own if own is not None else (request.query_params.get('branch') or '').strip()
        # بدون branch (فقط مدیر آموزش) = گزارش «ملی» روی همه‌ی شعب و استان‌ها
        branch = (canonical_branch_name(wanted) or wanted) if wanted else ''
        class_qs = ClassSurveyResponse.objects.select_related('enrollment', 'seminar_enrollment')
        general_qs = GeneralSurveyResponse.objects.all()
        if branch:
            class_qs = class_qs.filter(branch=branch)
            general_qs = general_qs.filter(branch=branch)
        class_resp = list(class_qs)
        general_resp = list(general_qs)
        held = set()
        voters = set()
        votes = {label: 0 for label in STANDARD_VOTES}
        for r in class_resp:
            if r.seminar_enrollment_id:
                held.add(('seminar', r.seminar_enrollment.seminar_id if r.seminar_enrollment else r.class_name))
            else:
                held.add(('class', r.enrollment.class_obj_id if r.enrollment and r.enrollment.class_obj_id else r.class_name))
            voters.add(('m', r.member_id))
        for r in general_resp:
            held.add(('general', r.survey_id))
            voters.add(('m', r.member_id))
        for r in class_resp + general_resp:
            for a in r.answers:
                if a.get('kind') == 'choice' and a.get('answer') in votes:
                    votes[a['answer']] += 1
        return Response({
            'branch': branch, 'national': not branch, 'surveys_held': len(held), 'voters': len(voters),
            'veryGood': votes['خیلی خوب'], 'good': votes['خوب'], 'average': votes['متوسط'],
            'bad': votes['بد'], 'veryBad': votes['خیلی بد'],
        })


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
        # ?class_id=  => فقط پاسخ‌های همان کلاس، با سؤال‌های فعلیِ همان کلاس (اختصاصی یا قالب)
        class_id = request.query_params.get('class_id')
        if class_id:
            klass = Class.objects.filter(pk=class_id).first() if str(class_id).isdigit() else None
            if klass is None:
                return Response({'detail': 'کلاس پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
            responses = responses.filter(enrollment__class_obj=klass)
            result_questions = effective_questions(klass)
        elif request.query_params.get('seminar_id'):
            # ?seminar_id= => پاسخ‌های یک سمینار/کارگاه (سؤال‌ها: قالب کلی)
            sid = request.query_params.get('seminar_id')
            if not str(sid).isdigit() or not Seminar.objects.filter(pk=sid).exists():
                return Response({'detail': 'سمینار پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
            responses = responses.filter(seminar_enrollment__seminar_id=sid)
            result_questions = list(ClassSurvey.load().questions.all())
        else:
            result_questions = list(ClassSurvey.load().questions.all())
        if staff_role(request.user) == ROLE_OFFICER:
            branch = canonical_branch_name(request.user.employee.branch)
            responses = responses.filter(branch=branch) if branch else responses.none()
        else:
            # ?branch= => مدیر آموزش فقط پاسخ‌های یک شعبه را می‌بیند (گزارش هر شعبه)
            wanted = (request.query_params.get('branch') or '').strip()
            if wanted:
                responses = responses.filter(branch=canonical_branch_name(wanted) or wanted)
        responses = list(responses)   # از جدیدترین به قدیمی‌ترین (ترتیب Meta)

        questions = []
        for q in result_questions:
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


# ---------------------------------------------------------------------------
# نظرسنجی «هر کلاس»: قالب مشترک + سؤال‌های اختصاصی یک کلاس
# ---------------------------------------------------------------------------
#   GET    /api/feedback/class-survey/classes/<class_id>/            -> سؤال‌های مؤثر آن کلاس (اختصاصی، وگرنه قالب)  [هر کاربر واردشده]
#   POST   /api/feedback/class-survey/classes/<class_id>/customize/  -> شخصی‌سازی: کپی قالب برای همین کلاس            [مدیر/مسئولِ همان شعبه]
#   DELETE /api/feedback/class-survey/classes/<class_id>/customize/  -> بازگشت به قالب مشترک (حذف سؤال‌های اختصاصی)  [همان]
#   GET/POST/PATCH/DELETE /api/feedback/class-survey/class-questions/ -> مدیریت سؤال‌های اختصاصی (?class_id=)       [همان]

def _manageable_class_or_error(request, class_id):
    """کلاس را برمی‌گرداند؛ مسئول آموزش فقط کلاس‌های شعبه‌ی خودش را می‌تواند مدیریت کند. (کلاس، None) یا (None، Response)."""
    klass = Class.objects.filter(pk=class_id).first() if str(class_id).isdigit() else None
    if klass is None:
        return None, Response({'detail': 'کلاس پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
    own = officer_branch_name(request.user)
    if own is not None and not same_branch(klass.branch, own):
        return None, Response({'detail': 'این کلاس مربوط به شعبه‌ی شما نیست.'}, status=status.HTTP_403_FORBIDDEN)
    return klass, None


class ClassSurveyForClassView(APIView):
    """سؤال‌های نظرسنجیِ یک کلاس؛ دانش‌پژوه هم برای پر کردن آن را می‌خواند."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, class_id):
        klass = Class.objects.filter(pk=class_id).first()
        if klass is None:
            return Response({'detail': 'کلاس پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        survey = ClassSurvey.load()
        custom = klass.survey_questions.exists()
        return Response({
            'class_id': klass.id,
            'class_name': klass.name,
            'custom': custom,
            'title': survey.title,
            'description': survey.description,
            'questions': ClassSurveyQuestionSerializer(effective_questions(klass), many=True).data,
        })


class ClassSurveyCustomizeView(APIView):
    """شخصی‌سازی نظرسنجی یک کلاس: کپی قالب (POST) یا بازگشت به قالب مشترک (DELETE)."""
    permission_classes = [IsEducationStaff]

    def post(self, request, class_id):
        klass, error = _manageable_class_or_error(request, class_id)
        if error:
            return error
        if klass.survey_questions.exists():
            return Response({'detail': 'این کلاس از قبل سؤال اختصاصی دارد.'}, status=status.HTTP_409_CONFLICT)
        with transaction.atomic():
            for position, q in enumerate(ClassSurvey.load().questions.all(), start=1):
                ClassSurveyQuestion.objects.create(
                    class_obj=klass, text=q.text, kind=q.kind, options=list(q.options), order=position,
                )
        record(request, 'survey', 'class_survey_customize', f'شخصی‌سازی نظرسنجی کلاس «{klass.name}»',
               target_type='نظرسنجی', target_label=klass.name, branch=klass.branch)
        return Response({'detail': 'نظرسنجی این کلاس از قالب کپی شد و قابل ویرایش است.'}, status=status.HTTP_201_CREATED)

    def delete(self, request, class_id):
        klass, error = _manageable_class_or_error(request, class_id)
        if error:
            return error
        deleted, _ = klass.survey_questions.all().delete()
        if deleted:
            record(request, 'survey', 'class_survey_reset', f'بازگشت نظرسنجی کلاس «{klass.name}» به قالب مشترک',
                   target_type='نظرسنجی', target_label=klass.name, branch=klass.branch)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomizedClassesView(APIView):
    """شناسه‌ی کلاس‌هایی که نظرسنجی اختصاصی دارند (بقیه از قالب کلی استفاده می‌کنند)."""
    permission_classes = [IsEducationStaff]

    def get(self, request):
        ids = ClassSurveyQuestion.objects.filter(class_obj__isnull=False).values_list('class_obj_id', flat=True).distinct()
        return Response({'class_ids': sorted(set(ids))})


class ClassSpecificQuestionViewSet(viewsets.ModelViewSet):
    """افزودن/ویرایش/حذف/جابه‌جایی سؤال‌های اختصاصیِ یک کلاس (مدیر؛ مسئول فقط کلاس‌های شعبه‌ی خودش)."""
    serializer_class = ClassSpecificQuestionSerializer
    permission_classes = [IsEducationStaff]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = ClassSurveyQuestion.objects.filter(class_obj__isnull=False).select_related('class_obj')
        class_id = self.request.query_params.get('class_id')
        if class_id and str(class_id).isdigit():
            qs = qs.filter(class_obj_id=class_id)
        own = officer_branch_name(self.request.user)
        if own is not None:
            ids = [pk for pk, br in qs.values_list('pk', 'class_obj__branch') if same_branch(br, own)]
            qs = qs.filter(pk__in=ids)
        return qs

    def perform_create(self, serializer):
        klass = serializer.validated_data['class_obj']
        own = officer_branch_name(self.request.user)
        if own is not None and not same_branch(klass.branch, own):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('این کلاس مربوط به شعبه‌ی شما نیست.')
        last = klass.survey_questions.aggregate(m=Max('order'))['m'] or 0
        obj = serializer.save(order=last + 1)
        record(self.request, 'survey', 'class_survey_q_create', f'افزودن سؤال به نظرسنجی کلاس «{klass.name}»',
               target_type='نظرسنجی', target_label=(obj.text or '')[:60], branch=klass.branch)

    def perform_update(self, serializer):
        obj = serializer.save()
        record(self.request, 'survey', 'class_survey_q_update', f'ویرایش سؤال نظرسنجی کلاس «{obj.class_obj.name}»',
               target_type='نظرسنجی', target_label=(obj.text or '')[:60], branch=obj.class_obj.branch)

    def perform_destroy(self, instance):
        klass = instance.class_obj
        label = (instance.text or '')[:60]
        instance.delete()
        record(self.request, 'survey', 'class_survey_q_delete', f'حذف سؤال از نظرسنجی کلاس «{klass.name}»',
               target_type='نظرسنجی', target_label=label, branch=klass.branch)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """ترتیب جدید سؤال‌های یک کلاس: {"class_id": 3, "ids": [..]} - باید دقیقاً همه‌ی سؤال‌های آن کلاس باشد."""
        klass, error = _manageable_class_or_error(request, request.data.get('class_id'))
        if error:
            return error
        ids = request.data.get('ids')
        current = set(klass.survey_questions.values_list('id', flat=True))
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) != current:
            return Response({'detail': 'فهرست سؤال‌ها برای تغییر ترتیب معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for position, question_id in enumerate(ids, start=1):
                ClassSurveyQuestion.objects.filter(pk=question_id).update(order=position)
        return Response(self.get_serializer(klass.survey_questions.all(), many=True).data)


# ---------------------------------------------------------------------------
# نظرسنجی‌های کلی (دلخواه)
# ---------------------------------------------------------------------------
#   GET    /api/feedback/general-surveys/                  -> فهرست (مدیر/مسئول: همه؛ دانش‌پژوه: فقط فعال‌های دارای سؤال)
#   POST   /api/feedback/general-surveys/                  -> ساخت (فقط مدیر آموزش) - همراه فهرست سؤال‌ها
#   PUT/PATCH/DELETE /api/feedback/general-surveys/<id>/   -> ویرایش/حذف (فقط مدیر آموزش)
#   GET    /api/feedback/general-surveys/my-status/        -> شناسه‌ی نظرسنجی‌هایی که خودم شرکت کرده‌ام (دانش‌پژوه)
#   POST   /api/feedback/general-surveys/<id>/submit/      -> شرکت (دانش‌پژوه؛ هر نفر فقط یک‌بار)
#   GET    /api/feedback/general-surveys/<id>/results/     -> نتایج (فقط مدیر آموزش)

def aggregate_results(questions, responses):
    """
    شمارش پاسخ‌ها برای فهرست سؤال‌ها: تستی = شمارش هر گزینه (گزینه‌ی حذف/ویرایش‌شده هم با پاسخ‌های قدیمی می‌ماند)،
    تشریحی = ۵۰ پاسخ متنیِ آخر. responses: لیستی از اشیایی با answers/submitted_at (و اختیاری class_name/branch).
    """
    items = []
    for q in questions:
        entries = []
        for r in responses:
            for a in r.answers:
                if a.get('question_id') == q.id and (a.get('answer') or '').strip():
                    entries.append((a['answer'], r))
        item = {'id': q.id, 'text': q.text, 'kind': q.kind, 'answered': len(entries)}
        if q.kind == 'choice':
            counts = {label: 0 for label in q.options}
            for answer, _ in entries:
                counts[answer] = counts.get(answer, 0) + 1
            item['options'] = [{'label': label, 'count': count} for label, count in counts.items()]
        else:
            item['answers'] = [
                {'text': answer, 'class_name': getattr(r, 'class_name', ''), 'branch': getattr(r, 'branch', ''),
                 'submitted_at': r.submitted_at}
                for answer, r in entries[:50]
            ]
        items.append(item)
    return items


class GeneralSurveyViewSet(viewsets.ModelViewSet):
    serializer_class = GeneralSurveySerializer
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'results'):
            return [IsEducationManager()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = GeneralSurvey.objects.prefetch_related('questions')
        if staff_role(self.request.user) is None:
            # دانش‌پژوه فقط نظرسنجی‌های فعالِ دارای سؤال را می‌بیند
            qs = qs.filter(is_active=True, questions__isnull=False).distinct()
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        record(self.request, 'survey', 'general_survey_create', f'ایجاد نظرسنجی کلی «{obj.title}»',
               target_type='نظرسنجی', target_label=obj.title)

    def perform_update(self, serializer):
        obj = serializer.save()
        record(self.request, 'survey', 'general_survey_update', f'ویرایش نظرسنجی کلی «{obj.title}»',
               target_type='نظرسنجی', target_label=obj.title)

    def perform_destroy(self, instance):
        title = instance.title
        instance.delete()
        record(self.request, 'survey', 'general_survey_delete', f'حذف نظرسنجی کلی «{title}»',
               target_type='نظرسنجی', target_label=title)

    @action(detail=False, methods=['get'], url_path='my-status')
    def my_status(self, request):
        member = _member_or_403(request)
        if member is None:
            return Response({'detail': 'فقط دانش‌پژوه به این بخش دسترسی دارد.'}, status=status.HTTP_403_FORBIDDEN)
        ids = GeneralSurveyResponse.objects.filter(member=member).values_list('survey_id', flat=True)
        return Response({'completed_survey_ids': list(ids)})

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        member = _member_or_403(request)
        if member is None:
            return Response({'detail': 'فقط دانش‌پژوه می‌تواند در نظرسنجی شرکت کند.'}, status=status.HTTP_403_FORBIDDEN)
        survey = self.get_object()          # نظرسنجی غیرفعال/بدون سؤال برای دانش‌پژوه ۴۰۴ است
        serializer = GeneralSurveySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        questions = list(survey.questions.all())
        snapshot = snapshot_answers(questions, serializer.validated_data['answers'])
        already = Response({'detail': 'شما قبلاً در این نظرسنجی شرکت کرده‌اید.'}, status=status.HTTP_409_CONFLICT)
        if GeneralSurveyResponse.objects.filter(survey=survey, member=member).exists():
            return already
        try:
            with transaction.atomic():
                GeneralSurveyResponse.objects.create(
                    survey=survey, member=member,
                    branch=canonical_branch_name(member.branch or '') or (member.branch or ''),
                    answers=snapshot,
                )
        except IntegrityError:
            return already
        record(request, 'survey', 'general_survey_submit', f'شرکت در نظرسنجی کلی «{survey.title}»',
               target_type='نظرسنجی', target_label=survey.title, branch=member.branch)
        return Response({'detail': 'از شرکت شما در نظرسنجی سپاسگزاریم.'}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        survey = self.get_object()
        responses = survey.responses.all()
        # ?branch= => فقط پاسخ‌های دانش‌پژوهان همان شعبه (گزارش هر شعبه)
        wanted = (request.query_params.get('branch') or '').strip()
        if wanted:
            responses = responses.filter(branch=canonical_branch_name(wanted) or wanted)
        responses = list(responses)
        return Response({
            'id': survey.id, 'title': survey.title,
            'participants': len(responses),
            'questions': aggregate_results(list(survey.questions.all()), responses),
        })
