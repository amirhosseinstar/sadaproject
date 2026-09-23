# ===== مسیر این فایل در پروژه: class_management/views.py (کنار manage.py) =====
"""
API دپارتمان‌ها، کلاس‌ها و ثبت‌نام.

  GET/POST/DELETE  /api/classmgmt/departments/            -> دپارتمان‌ها
  GET/POST/DELETE  /api/classmgmt/branch-departments/      -> کدام دپارتمان در کدام شعبه فعال است
                     (?branch=... برای فیلتر)

  GET/POST/PUT/DELETE /api/classmgmt/classes/              -> کلاس‌ها
                     (?department=..&branch=..&gender=..&published=..&term=.. برای فیلتر)
  POST /api/classmgmt/classes/<id>/enroll/                 -> ثبت‌نام یک دانش‌پژوه در این کلاس
                     بدنه: national_id, membership_code
                     همین‌جا هویت را هم تأیید می‌کند (عضو هست؟ محروم نیست؟
                     عضویتش معتبر است؟ ظرفیت خالی هست؟) - نقطه‌ی واحد ثبت‌نام.

  GET /api/classmgmt/classes/<id>/students/                -> لیست دانش‌پژوهان ثبت‌نامی این کلاس

TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل بقیه‌ی این پروژه، فعلاً نوشتن
برای همه باز است چون پنل ادمین HTML هنوز خودش وارد نمی‌شود.
"""

from django.db import transaction
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Employee
from core.permissions import ROLE_OFFICER, IsEducationStaff, staff_role
from feedback.branches import canonical_branch_name
from logs import throttle
from logs.mixins import AuditedMixin, audit
from logs.recorder import record, record_dedup
from members.models import Member

from .eligibility import check_age_eligibility
from .models import BranchDepartment, Class, Department, Enrollment, Lesson, Question, SiteSettings, TeacherLessonPermission
from .serializers import (
    BranchDepartmentSerializer,
    ClassSerializer,
    DepartmentSerializer,
    EnrollmentSerializer,
    LessonSerializer,
    QuestionSerializer,
    SiteSettingsSerializer,
)


class SiteSettingsView(APIView):
    """
    تنظیمات سراسری سایت (فعلاً فقط «دسترسی همگان به دیدن و ثبت‌نام در
    کلاس‌ها»). چون فقط یک رکورد وجود دارد، GET همیشه همان یکی را برمی‌گرداند
    و PATCH همان را به‌روز می‌کند - نیازی به id در URL نیست.

    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): طبق متن خودِ پنل ادمین، این
    فقط باید توسط «مدیر آموزش» قابل تغییر باشد؛ فعلاً مثل بقیه‌ی پروژه
    برای راحتی توسعه باز است.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(SiteSettingsSerializer(SiteSettings.load()).data)

    def patch(self, request):
        # کلید «انتقادات و پیشنهادات» طبق متن پنل فقط توسط «مدیر آموزش» قابل تغییر
        # است (مسئول آموزش فقط وضعیتش را می‌بیند) - این را در سرور اجبار می‌کنیم، نه
        # فقط در فرانت‌اند، چون دکمه‌ی فرانت‌اند به‌سادگی دور زده می‌شود.
        if 'feedback_enabled' in request.data:
            user = request.user
            employee = getattr(user, 'employee', None) if user.is_authenticated else None
            is_manager = user.is_authenticated and (
                user.is_superuser or (employee is not None and employee.role == 'مدیر آموزش')
            )
            if not is_manager:
                return Response(
                    {'detail': 'فقط مدیر آموزش می‌تواند بخش انتقادات و پیشنهادات را فعال/غیرفعال کند.'},
                    status=403,
                )
        settings_obj = SiteSettings.load()
        serializer = SiteSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {name: getattr(settings_obj, name) for name in serializer.validated_data}
        serializer.save()
        # تغییر تنظیمات سایت (مثلاً کلید انتقادات و پیشنهادات) در لاگ ثبت می‌شود
        changes = [
            {'field': str(SiteSettings._meta.get_field(name).verbose_name), 'old': str(before[name]), 'new': str(value)}
            for name, value in serializer.validated_data.items() if before[name] != value
        ]
        if changes:
            record(request, 'settings', 'settings_update', 'تغییر تنظیمات سایت', target_type='تنظیمات', changes=changes)
        return Response(serializer.data)


@audit('class', 'دپارتمان', {
    'create': ('department_create', 'افزودن دپارتمان'),
    'destroy': ('department_delete', 'حذف دپارتمان'),
})
class DepartmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']


@audit('class', 'درس', {
    'create': ('lesson_create', 'افزودن درس'),
    'update': ('lesson_update', 'ویرایش درس'),
    'destroy': ('lesson_delete', 'حذف درس'),
})
class LessonViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    درس (سرفصل) - قبل از ساخت هر کلاسی باید درسش اینجا تعریف شده باشد.
    """
    queryset = Lesson.objects.select_related('department').all()
    serializer_class = LessonSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get('department')
        if department:
            qs = qs.filter(department_id=department)
        return qs


@audit('class', 'سؤال آزمون', {
    'create': ('question_create', 'افزودن سؤال آزمون'),
    'update': ('question_update', 'ویرایش سؤال آزمون'),
    'destroy': ('question_delete', 'حذف سؤال آزمون'),
}, label_func=lambda q: (q.text or '')[:60], branch_func=lambda q: q.lesson.branch if q.lesson else '', skip_fields=('lesson',))
class QuestionViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    بانک سوالات یک درس - همیشه با ?lesson=<id> فیلتر می‌شود (صفحه‌ی «بانک
    سوالات» همیشه اول یک درس را انتخاب کرده، بعد سوالاتش را می‌بیند).
    """
    queryset = Question.objects.select_related('lesson').all()
    serializer_class = QuestionSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        lesson = self.request.query_params.get('lesson')
        if lesson:
            qs = qs.filter(lesson_id=lesson)
        return qs


@audit('class', 'دپارتمان شعبه', {
    'create': ('branch_department_create', 'فعال‌کردن دپارتمان برای شعبه'),
    'destroy': ('branch_department_delete', 'غیرفعال‌کردن دپارتمان برای شعبه'),
}, label_func=lambda b: f'{b.department.name} — {b.branch}', skip_fields=('department',))
class BranchDepartmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    queryset = BranchDepartment.objects.select_related('department').all()
    serializer_class = BranchDepartmentSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch=branch)
        return qs


def _log_enroll_rejected(request, cls, member, reason):
    """
    رد شدنِ ثبت‌نام (محروم، عضویت منقضی، رده سنی، استان، پیش‌نیاز، ظرفیت، تکراری) در لاگ ثبت می‌شود تا
    مسئول ببیند چرا دانش‌پژوهی نتوانسته ثبت‌نام کند. تکرارِ عینِ همان رد شدن در ۱۰ دقیقه دوباره ثبت نمی‌شود.
    (کد ملی ثبت می‌شود، کد عضویت هرگز.)
    """
    name = f'{member.user.first_name} {member.user.last_name}'.strip() or member.national_id
    record_dedup(
        request, 'class', 'enroll_rejected', f'رد شدن ثبت‌نام «{name}» در «{cls.name}»: {reason}',
        status='failed', target_type='کلاس', target_id=str(cls.pk), target_label=cls.name,
        branch=cls.branch, identifier=member.national_id,
    )


def _class_summary(action_key, label, target_label, obj, request, response):
    if action_key == 'enroll':
        national_id = request.data.get('national_id', '') if hasattr(request.data, 'get') else ''
        return f'{label}: کد ملی {national_id} در «{target_label}»'
    return f'{label}: {target_label}' if target_label else label


@audit('class', 'کلاس', {
    'create': ('class_create', 'درج کلاس'),
    'update': ('class_update', 'ویرایش کلاس'),
    'destroy': ('class_delete', 'حذف کلاس'),
    'enroll': ('class_enroll', 'ثبت‌نام دانش‌پژوه در کلاس'),
}, summary_func=_class_summary, skip_fields=('lesson', 'department', 'term', 'teacher', 'prerequisite'))
class ClassViewSet(AuditedMixin, viewsets.ModelViewSet):
    queryset = Class.objects.select_related('department', 'teacher').all()
    serializer_class = ClassSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        department = params.get('department')
        department_name = params.get('department_name')
        branch = params.get('branch')
        gender = params.get('gender')
        published = params.get('published')
        term = params.get('term')
        class_type = params.get('type')
        is_national = params.get('is_national')
        mine = params.get('mine')

        if department:
            qs = qs.filter(department_id=department)
        if department_name:
            qs = qs.filter(department__name__icontains=department_name)
        if class_type:
            qs = qs.filter(class_type=class_type)
        if is_national is not None:
            qs = qs.filter(is_national=is_national.lower() in ('1', 'true', 'yes'))
        if branch:
            qs = qs.filter(branch=branch)
        if gender:
            # کلاس «مختلط» برای هر دو جنسیت هم نمایش داده می‌شود
            qs = qs.filter(gender__in=[gender, 'مختلط'])
        if published is not None:
            qs = qs.filter(is_published=published.lower() in ('1', 'true', 'yes'))
        if term:
            qs = qs.filter(term_id=term)
        if mine is not None and mine.lower() in ('1', 'true', 'yes'):
            # نکته‌ی امنیتی: بر خلاف بقیه‌ی فیلترها، این یکی به شناسه‌ای که
            # کلاینت می‌فرستد اعتماد نمی‌کند - از روی خودِ نشستِ واردشده
            # (request.user.employee) مدرس را پیدا می‌کند تا هیچ مدرسی
            # نتواند با فرستادن یک id دیگر کلاس‌های مدرس دیگری را ببیند.
            request = self.request
            if request.user.is_authenticated and hasattr(request.user, 'employee'):
                qs = qs.filter(teacher=request.user.employee)
            else:
                qs = qs.none()
        return qs

    @action(detail=True, methods=['get'])
    def students(self, request, pk=None):
        cls = self.get_object()
        enrollments = cls.enrollments.select_related('member', 'member__user').all()
        return Response(EnrollmentSerializer(enrollments, many=True).data)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        """
        نقطه‌ی واحد ثبت‌نام: هم هویت/محرومیت/اعتبار عضویت را چک می‌کند، هم
        ظرفیت کلاس را، هم واقعاً رکورد ثبت‌نام را می‌سازد - دقیقاً همان
        چیزی که ویزارد ثبت‌نام دوره (hozori-courses.html/majazi-courses.html)
        باید در «مرحله‌ی موفقیت» صدا بزند.
        """
        cls = self.get_object()

        # مدیر/مسئول آموزش (نیروی انسانی) حتی اگر هفته‌ی ثبت‌نام هم گذشته
        # باشد، باید بتواند از پنل خودش دستی دانش‌پژوه اضافه کند؛ این
        # محدودیت فقط برای ثبت‌نام عمومی (خودِ دانش‌پژوهان از سایت اصلی) است
        is_staff_request = request.user.is_authenticated and hasattr(request.user, 'employee')

        if not is_staff_request and not SiteSettings.load().public_registration_enabled:
            return Response(
                {'detail': 'در حال حاضر ثبت‌نام در کلاس‌ها برای عموم بسته است.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        national_id = (request.data.get('national_id') or '').strip()
        membership_code = (request.data.get('membership_code') or '').strip()
        if not national_id or not membership_code:
            return Response({'detail': 'کد ملی و کد عضویت لازم است.'}, status=status.HTTP_400_BAD_REQUEST)

        # جفتِ کد ملی + کد عضویت را می‌سنجد؛ کد عضویت همان رمز ورود دانش‌پژوه است، پس جفت غلط (فقط برای
        # ثبت‌نام عمومی) مثل ورود ناموفق شمرده و بعد از چند بار مسدود می‌شود. مدیر/مسئول معاف‌اند.
        ctx = None
        if not is_staff_request:
            ctx, blocked = throttle.guard(national_id)
            if blocked:
                return blocked

        member = (
            Member.objects
            .filter(national_id=national_id, membership_code=membership_code)
            .select_related('ban')
            .first()
        )
        if member is None:
            not_found = 'این کد ملی و کد عضویت در سامانه‌ی اعضا یافت نشد.'
            if ctx is None:
                return Response({'is_member': False, 'detail': not_found}, status=status.HTTP_400_BAD_REQUEST)
            response = throttle.fail(request, ctx, 'identity_failed', 'تلاش ناموفق برای تأیید هویت هنگام ثبت‌نام (کد ملی و کد عضویت نخواند)',
                                     not_found, status.HTTP_400_BAD_REQUEST)
            if response.status_code == status.HTTP_400_BAD_REQUEST:
                response.data['is_member'] = False
            return response
        if ctx is not None:
            throttle.register_success(ctx['key'])
        if hasattr(member, 'ban'):
            _log_enroll_rejected(request, cls, member, 'عضو محروم است')
            return Response(
                {'is_member': True, 'is_banned': True, 'ban_reason': member.ban.reason, 'detail': 'این عضو محروم شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not member.is_membership_valid:
            _log_enroll_rejected(request, cls, member, 'عضویت منقضی شده است')
            return Response(
                {'is_member': True, 'is_valid': False, 'detail': 'عضویت این فرد منقضی شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # رده سنی کلاس (اگر دارد): اطلاعات عضو باید کامل باشد و سنش (از روی تاریخ
        # تولد) داخل بازه‌ی کلاس باشد؛ این چک سمت سرور است و از هیچ مسیری
        # (سایت اصلی یا پنل ادمین/مسئول) دور زده نمی‌شود
        age_error = check_age_eligibility(member, cls)
        if age_error:
            _log_enroll_rejected(request, cls, member, age_error.get('detail') or 'رده سنی/اطلاعات ناقص')
            return Response(age_error, status=status.HTTP_400_BAD_REQUEST)
        # هر دانش‌پژوه فقط می‌تواند در کلاس‌های استان خودش ثبت‌نام کند (چه
        # حضوری چه مجازی) - به‌جز کلاس‌های مجازی «سراسری» (is_national=True)
        # که برای همه‌ی استان‌ها آزاد است
        if not cls.is_national:
            from core.models import Branch
            class_branch = Branch.objects.filter(name=cls.branch).first()
            class_province = class_branch.province if class_branch else None
            if class_province and member.province and class_province != member.province:
                _log_enroll_rejected(request, cls, member, f'استان دانش‌پژوه ({member.province}) با استان کلاس ({class_province}) نمی‌خواند')
                return Response(
                    {
                        'detail': f'این کلاس در استان «{class_province}» برگزار می‌شود؛ شما فقط می‌توانید در کلاس‌های استان «{member.province}» ثبت‌نام کنید.',
                        'wrong_province': True,
                        'class_province': class_province,
                        'member_province': member.province,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if cls.prerequisite:
            # نکته‌ی مهم: صرفِ داشتن یک رکورد ثبت‌نام در درسِ پیش‌نیاز کافی
            # نیست - چون ممکن است آن‌جا غایب بوده یا مردود شده باشد. قبولی
            # دقیقاً همان قاعده‌ای است که در «سوابق آموزشی» هم استفاده می‌شود:
            # غایب نبوده و نمره‌اش حداقل ۷۵ (score > 74) بوده باشد.
            passed_prerequisite = Enrollment.objects.filter(
                lesson=cls.prerequisite, member=member, absent=False, score__gt=74,
            ).exists()
            if not passed_prerequisite:
                _log_enroll_rejected(request, cls, member, f'پیش‌نیاز «{cls.prerequisite.name}» را با نمره‌ی قبولی نگذرانده است')
                return Response(
                    {
                        'detail': 'برای ثبت‌نام در این کلاس، باید ابتدا درسِ پیش‌نیاز آن را با نمره‌ی قبولی گذرانده باشید.',
                        'prerequisite_required': True,
                        'prerequisite_id': cls.prerequisite.id,
                        'prerequisite_name': cls.prerequisite.name,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        # هر دانش‌پژوه در هر ترم حداکثر یک کلاس «حضوری» و یک کلاس «مجازی» می‌تواند ثبت‌نام کند؛
        # این محدودیت فقط برای ثبت‌نامِ عمومی (ویزارد سایت) است - مدیر/مسئول از پنل معاف‌اند.
        if not is_staff_request:
            same_type = (
                Enrollment.objects
                .filter(member=member, class_obj__isnull=False, class_obj__term=cls.term, class_obj__class_type=cls.class_type)
                .exclude(class_obj=cls)
                .select_related('class_obj')
                .first()
            )
            if same_type:
                other_name = same_type.class_obj.name
                _log_enroll_rejected(request, cls, member, f'قبلاً در کلاس {cls.class_type}ِ دیگری («{other_name}») در همین ترم ثبت‌نام کرده است')
                return Response(
                    {
                        'detail': f'شما «{other_name}» را ثبت‌نام کرده‌اید؛ در هر ترم فقط یک کلاس {cls.class_type} می‌توانید ثبت‌نام کنید.',
                        'already_enrolled_same_type': True,
                        'other_class_name': other_name,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if cls.is_full:
            _log_enroll_rejected(request, cls, member, 'ظرفیت کلاس تکمیل است')
            return Response({'detail': 'ظرفیت این کلاس تکمیل شده است.'}, status=status.HTTP_400_BAD_REQUEST)
        if Enrollment.objects.filter(class_obj=cls, member=member).exists():
            _log_enroll_rejected(request, cls, member, 'قبلاً در این کلاس ثبت‌نام کرده است')
            return Response(
                {'detail': 'قبلاً در این کلاس ثبت‌نام کرده‌اید.', 'already_enrolled': True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment = Enrollment.objects.create(class_obj=cls, lesson=cls.lesson, member=member)
        return Response(EnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)


def _enrollment_label(e):
    klass = e.class_obj.name if e.class_obj else (e.lesson.name if e.lesson else '')
    return f'{e.member.user.first_name} {e.member.user.last_name} — {klass}'.strip()


@audit('class', 'ثبت‌نام دانش‌پژوه', {
    'update': ('enrollment_update', 'ثبت/ویرایش نتیجه‌ی دانش‌پژوه در کلاس'),
    'destroy': ('enrollment_delete', 'حذف دانش‌پژوه از کلاس'),
}, label_func=_enrollment_label,
   branch_func=lambda e: (e.class_obj.branch if e.class_obj else (e.lesson.branch if e.lesson else '')),
   skip_fields=('member', 'class_obj', 'lesson'))
class EnrollmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    فقط برای مشاهده/حذف یک ثبت‌نام (مثلاً وقتی ادمین یک دانش‌پژوه را از
    کلاس حذف می‌کند) - ساخت ثبت‌نام همیشه باید از ClassViewSet.enroll باشد
    (که هویت/محرومیت/اعتبار/ظرفیت را هم چک می‌کند)، نه مستقیم از این‌جا.

    برای «سوابق آموزشی» (پنل ادمین)، با ?member_national_id= و/یا
    ?member_membership_code= فیلتر می‌شود.
    """
    queryset = (
        Enrollment.objects
        .select_related('member', 'member__user', 'class_obj', 'class_obj__department', 'class_obj__term', 'lesson', 'lesson__department')
        .all()
    )
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        national_id = self.request.query_params.get('member_national_id')
        membership_code = self.request.query_params.get('member_membership_code')
        if national_id:
            qs = qs.filter(member__national_id=national_id)
        if membership_code:
            qs = qs.filter(member__membership_code=membership_code)
        return qs


def _branch_key(name):
    """نام شعبه برای مقایسه: نام استانداردِ جدول شعب، وگرنه خودِ متن (بدون فاصله‌ی اضافه)."""
    return canonical_branch_name(name) or (name or '').strip()


class TeacherLessonPermissionView(APIView):
    """
    مجوزهای تدریس یک مدرس (فعال/غیرفعال‌کردن درس‌ها) - فقط مدیر/مسئول آموزش.

      GET   /api/classmgmt/teacher-permissions/?teacher=<id>
              -> {"teacher": id, "lesson_ids": [درس‌هایی که مجوزشان فعال است]}
      POST  /api/classmgmt/teacher-permissions/   {"teacher": id, "enable": [..], "disable": [..]}
              -> فعال/غیرفعال‌کردن چند درس با هم (اتمی)؛ همان پاسخ GET را برمی‌گرداند

    قواعد: فقط برای کسی که سمتش «مدرس» است؛ مسئول آموزش فقط برای مدرسین شعبه‌ی خودش؛ و هر
    درسِ فعال‌شده باید متعلق به شعبه‌ی همان مدرس باشد (درس‌ها هر شعبه جدا تعریف می‌شوند).
    """
    permission_classes = [IsEducationStaff]

    def _teacher(self, request, teacher_id):
        """مدرس را برمی‌گرداند یا (None, پاسخ خطا)."""
        try:
            teacher = Employee.objects.filter(pk=int(teacher_id), role='مدرس').first()
        except (TypeError, ValueError):
            teacher = None
        if teacher is None:
            return None, Response({'detail': 'مدرس پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        if staff_role(request.user) == ROLE_OFFICER:
            officer_branch = _branch_key(request.user.employee.branch)
            if not officer_branch or _branch_key(teacher.branch) != officer_branch:
                return None, Response({'detail': 'شما فقط به مدرسین شعبه‌ی خودتان دسترسی دارید.'},
                                      status=status.HTTP_403_FORBIDDEN)
        return teacher, None

    @staticmethod
    def _payload(teacher):
        ids = list(TeacherLessonPermission.objects.filter(teacher=teacher).values_list('lesson_id', flat=True))
        return {'teacher': teacher.id, 'lesson_ids': sorted(ids)}

    def get(self, request):
        teacher, error = self._teacher(request, request.query_params.get('teacher'))
        if error:
            return error
        return Response(self._payload(teacher))

    def post(self, request):
        teacher, error = self._teacher(request, request.data.get('teacher'))
        if error:
            return error

        def id_list(key):
            value = request.data.get(key, [])
            if not isinstance(value, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in value):
                raise ValueError(key)
            return set(value)

        try:
            enable, disable = id_list('enable'), id_list('disable')
        except ValueError:
            return Response({'detail': 'فهرست درس‌ها معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        if enable & disable:
            return Response({'detail': 'یک درس نمی‌تواند هم‌زمان فعال و غیرفعال شود.'}, status=status.HTTP_400_BAD_REQUEST)

        lessons = {l.id: l for l in Lesson.objects.filter(pk__in=enable)}
        if set(lessons) != enable:
            return Response({'detail': 'یکی از درس‌ها پیدا نشد.'}, status=status.HTTP_400_BAD_REQUEST)
        teacher_branch = _branch_key(teacher.branch)
        for lesson in lessons.values():
            if _branch_key(lesson.branch) != teacher_branch:
                return Response(
                    {'detail': f'درس «{lesson.name}» متعلق به شعبه‌ی این مدرس نیست.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            before_ids = set(TeacherLessonPermission.objects.filter(teacher=teacher).values_list('lesson_id', flat=True))
            for lesson_id in enable:
                TeacherLessonPermission.objects.get_or_create(teacher=teacher, lesson_id=lesson_id)
            TeacherLessonPermission.objects.filter(teacher=teacher, lesson_id__in=disable).delete()
        # فقط تغییرهای واقعی (درسی که واقعاً فعال/غیرفعال شد) در لاگ می‌آید
        turned_on = [l for l_id, l in lessons.items() if l_id not in before_ids]
        turned_off = list(Lesson.objects.filter(pk__in=(disable & before_ids)))
        changes = [{'field': l.name, 'old': 'غیرفعال', 'new': 'فعال'} for l in turned_on] + \
                  [{'field': l.name, 'old': 'فعال', 'new': 'غیرفعال'} for l in turned_off]
        if changes:
            record(request, 'teacher', 'teacher_permission_update', f'ویرایش مجوزهای تدریس مدرس: {teacher.name}',
                   target_type='مدرس', target_id=str(teacher.pk), target_label=teacher.name, branch=teacher.branch, changes=changes)
        return Response(self._payload(teacher))
