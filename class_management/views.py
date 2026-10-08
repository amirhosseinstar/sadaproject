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

امنیت (قاعده‌ی کلی این فایل):
  - خواندنِ داده‌ی عمومی (دپارتمان، درس، کلاس، سمینار، ترم) برای همه باز است چون صفحه‌های عمومی سایت لازم دارند.
  - هر نوشتن فقط برای مدیر/مسئول آموزش است؛ مسئول آموزش فقط در شعبه‌ی خودش می‌نویسد.
  - ثبت‌نام (enroll) عمومی است ولی هویت (کد ملی + کد عضویت) و محدودیت تلاش دارد.
  - اطلاعات شخصی (لیست دانش‌پژوهان کلاس، ثبت‌نام‌ها و نمره‌ها، بانک سؤال) فقط برای کارکنان یا صاحب اطلاعات
    (دانش‌پژوه: خودش؛ مدرس: کلاس‌های خودش) قابل دسترسی است.
"""

from django.db import transaction
from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Employee
from core.permissions import (
    IsEducationManager, ROLE_OFFICER, IsEducationStaff, ReadOnlyOrEducationManager, ReadOnlyOrEducationStaff, branch_values, member_of,
    officer_branch_name, same_branch, scope_to_officer_branch, staff_role, teacher_employee,
)
from feedback.branches import canonical_branch_name
from logs import throttle
from logs.mixins import AuditedMixin, audit
from logs.recorder import actor_info, record, record_dedup
from members.models import Member

from .eligibility import check_age_eligibility
from .models import (
    BranchDepartment, Class, Department, Enrollment, Lesson, Question, Seminar, SeminarEnrollment, SiteSettings,
    Announcement, Slide, TeacherLessonPermission,
)
from .serializers import (
    BranchDepartmentSerializer,
    ClassSerializer,
    DepartmentSerializer,
    EnrollmentSerializer,
    LessonSerializer,
    QuestionSerializer,
    SeminarEnrollmentSerializer,
    SeminarSerializer,
    AnnouncementSerializer,
    SiteSettingsSerializer,
    SlideSerializer,
    SlideSettingsSerializer,
)


class OfficerBranchWriteMixin:
    """
    مسئول آموزش فقط روی رکوردهای «شعبه‌ی خودش» می‌نویسد (ساخت/ویرایش/حذف)؛ مدیر محدودیتی ندارد.
    خواندن (عمومی) و اکشن ثبت‌نام (enroll) محدود نمی‌شود.
    فیلد شعبه‌ی مدل با officer_branch_field مشخص می‌شود (پیش‌فرض: branch).
    """
    officer_branch_field = 'branch'

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.method not in permissions.SAFE_METHODS and getattr(self, 'action', None) != 'enroll':
            qs = scope_to_officer_branch(qs, self.request.user, self.officer_branch_field)
        return qs

    def _officer_check_branch(self, branch):
        own = officer_branch_name(self.request.user)
        if own is not None and not same_branch(branch, own):
            raise PermissionDenied('شما فقط در شعبه‌ی خودتان می‌توانید ثبت یا ویرایش کنید.')

    def perform_create(self, serializer):
        self._officer_check_branch(serializer.validated_data.get('branch'))
        super().perform_create(serializer)

    def perform_update(self, serializer):
        if 'branch' in serializer.validated_data:
            self._officer_check_branch(serializer.validated_data.get('branch'))
        super().perform_update(serializer)


class SiteSettingsView(APIView):
    """
    تنظیمات سراسری سایت (فعلاً فقط «دسترسی همگان به دیدن و ثبت‌نام در
    کلاس‌ها»). چون فقط یک رکورد وجود دارد، GET همیشه همان یکی را برمی‌گرداند
    و PATCH همان را به‌روز می‌کند - نیازی به id در URL نیست.

    امنیت: خواندن عمومی است (صفحه‌ها وضعیت ثبت‌نام را می‌پرسند)؛ تغییر فقط مدیر/مسئول آموزش
    (و کلید انتقادات و پیشنهادات فقط مدیر آموزش؛ در patch زیر اجبار می‌شود).
    """
    permission_classes = [ReadOnlyOrEducationStaff]

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
@audit('class', 'دپارتمان', {
    'create': ('department_create', 'افزودن دپارتمان'),
    'destroy': ('department_delete', 'حذف دپارتمان'),
})
class DepartmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [ReadOnlyOrEducationManager]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        # اختیاری: صفحه‌ی «مدیریت دوره و دپارتمان‌ها»ی حضوری و صفحه‌ی «کلاس‌های
        # مجازی» هرکدام فقط دپارتمان‌های نوع خودشان را می‌خواهند؛ وقتی این
        # پارامتر فرستاده نشود (مثل بقیه‌ی جاهایی که همه‌ی دپارتمان‌ها لازم‌اند،
        # مثل چک‌لیست دپارتمانِ مدرس)، رفتار قبلی (همه‌ی دپارتمان‌ها) حفظ می‌شود.
        class_type = self.request.query_params.get('class_type')
        if class_type:
            qs = qs.filter(class_type=class_type)
        return qs


@audit('class', 'درس', {
    'create': ('lesson_create', 'افزودن درس'),
    'update': ('lesson_update', 'ویرایش درس'),
    'destroy': ('lesson_delete', 'حذف درس'),
})
class LessonViewSet(AuditedMixin, OfficerBranchWriteMixin, viewsets.ModelViewSet):
    """
    درس (سرفصل) - قبل از ساخت هر کلاسی باید درسش اینجا تعریف شده باشد.
    """
    queryset = Lesson.objects.select_related('department').all()
    serializer_class = LessonSerializer
    permission_classes = [ReadOnlyOrEducationStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get('department')
        if department:
            qs = qs.filter(department_id=department)
        class_type = self.request.query_params.get('class_type')
        if class_type:
            qs = qs.filter(class_type=class_type)
        return qs


class IsEducationStaffOrTeacher(permissions.BasePermission):
    def has_permission(self, request, view):
        return staff_role(request.user) is not None or teacher_employee(request.user) is not None


class TeacherMyLessonsView(APIView):
    """درس‌هایی که مدرسِ واردشده مجوز درج سؤال برایشان دارد."""
    permission_classes = [IsEducationStaffOrTeacher]

    def get(self, request):
        teacher = teacher_employee(request.user)
        if teacher is None:
            return Response([])
        perms = TeacherLessonPermission.objects.filter(teacher=teacher).select_related('lesson', 'lesson__department')
        return Response([
            {'id': p.lesson_id, 'name': p.lesson.name, 'department': p.lesson.department.name,
             'branch': p.lesson.branch, 'question_count': p.lesson.questions.count()}
            for p in perms
        ])


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
    # امنیت: گزینه‌ها «پاسخ صحیح» را هم دارند؛ پس حتی خواندن هم فقط برای کارکنان است
    # کارکنان آموزش + مدرس (فقط برای درس‌هایی که در «ویرایش مجوزها» دارد)
    permission_classes = [IsEducationStaffOrTeacher]

    def _teacher_lesson_ids(self):
        teacher = teacher_employee(self.request.user)
        if teacher is None:
            return None
        return set(TeacherLessonPermission.objects.filter(teacher=teacher).values_list('lesson_id', flat=True))

    def get_queryset(self):
        qs = scope_to_officer_branch(super().get_queryset(), self.request.user, 'lesson__branch')
        allowed = self._teacher_lesson_ids()
        if allowed is not None:
            qs = qs.filter(lesson_id__in=allowed)
        lesson = self.request.query_params.get('lesson')
        if lesson:
            qs = qs.filter(lesson_id=lesson)
        return qs

    def _check_lesson_branch(self, serializer):
        lesson = serializer.validated_data.get('lesson')
        allowed = self._teacher_lesson_ids()
        if allowed is not None and (lesson is None or lesson.id not in allowed):
            raise PermissionDenied('برای این درس مجوز درج سؤال ندارید.')
        own = officer_branch_name(self.request.user)
        if own is not None and lesson is not None and not same_branch(lesson.branch, own):
            raise PermissionDenied('شما فقط برای درس‌های شعبه‌ی خودتان می‌توانید سؤال ثبت کنید.')

    def perform_create(self, serializer):
        self._check_lesson_branch(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._check_lesson_branch(serializer)
        super().perform_update(serializer)


@audit('class', 'دپارتمان شعبه', {
    'create': ('branch_department_create', 'فعال‌کردن دپارتمان برای شعبه'),
    'destroy': ('branch_department_delete', 'غیرفعال‌کردن دپارتمان برای شعبه'),
}, label_func=lambda b: f'{b.department.name} — {b.branch}', skip_fields=('department',))
class BranchDepartmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    queryset = BranchDepartment.objects.select_related('department').all()
    serializer_class = BranchDepartmentSerializer
    permission_classes = [ReadOnlyOrEducationManager]
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
}, summary_func=_class_summary, skip_fields=('lesson', 'department', 'term', 'teacher', 'prerequisite'))
class ClassViewSet(AuditedMixin, OfficerBranchWriteMixin, viewsets.ModelViewSet):
    queryset = Class.objects.select_related('department', 'teacher').all()
    serializer_class = ClassSerializer
    permission_classes = [ReadOnlyOrEducationStaff]

    def get_permissions(self):
        # ثبت‌نام عمومی است (هویت را خودش می‌سنجد)؛ لیست دانش‌پژوهان فقط با ورود (بررسی دقیق داخل action)
        if self.action == 'enroll':
            return [permissions.AllowAny()]
        if self.action == 'students':
            return [permissions.IsAuthenticated()]
        return [ReadOnlyOrEducationStaff()]

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
        # فقط کارکنان (مسئول: شعبه‌ی خودش) و مدرسِ همین کلاس؛ لیست شامل کد ملی و تلفن دانش‌پژوهان است
        teacher = teacher_employee(request.user)
        own = officer_branch_name(request.user)
        is_manager = staff_role(request.user) is not None and own is None
        is_officer_of_branch = own is not None and same_branch(cls.branch, own)
        is_class_teacher = teacher is not None and cls.teacher_id == teacher.id
        if not (is_manager or is_officer_of_branch or is_class_teacher):
            return Response({'detail': 'شما به لیست دانش‌پژوهان این کلاس دسترسی ندارید.'}, status=status.HTTP_403_FORBIDDEN)
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
        is_staff_request = staff_role(request.user) is not None

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
        # که برای همه‌ی استان‌ها آزاد است.
        #
        # نکته‌ی مهم: تطبیق نام شعبه با «نام استانداردِ جدول شعب» انجام می‌شود
        # (canonical_branch_name)، نه تطبیق دقیقِ رشته‌ای؛ وگرنه کوچک‌ترین اختلاف
        # (مثلاً حرف «ي» عربی به‌جای «ی» فارسی) باعث می‌شد استانِ کلاس اصلاً پیدا
        # نشود و این محدودیت بی‌صدا نادیده گرفته شود. اگر با همه‌ی این‌ها هم استانِ
        # کلاس پیدا نشود (داده‌ی ناقص/نامعتبر)، به‌جای بازگذاشتنِ بی‌صدا، ثبت‌نام رد
        # می‌شود - پیش‌فرض امن یعنی «اجازه نده» نه «اجازه بده».
        if not cls.is_national:
            from core.models import Branch

            canonical_class_branch = canonical_branch_name(cls.branch) or (cls.branch or '').strip()
            class_branch = Branch.objects.filter(name=canonical_class_branch).first()
            class_province = (class_branch.province if class_branch else '') or ''
            member_province = (member.province or '').strip()
            # این محدودیت فقط وقتی اجرا می‌شود که استانِ «هم کلاس و هم دانش‌پژوه» مشخص باشد؛
            # اگر شعبه‌ی کلاس در جدول شعب استانش ثبت نشده (فیلد «استان» آن خالی مانده)، این
            # قانون برای آن کلاس عملاً خاموش می‌ماند - نه این‌که ثبت‌نام را اشتباهی ببندد.
            if class_province and member_province and class_province != member_province:
                _log_enroll_rejected(
                    request, cls, member,
                    f'استان کلاس ({class_province}) با استان دانش‌پژوه ({member_province}) نمی‌خواند',
                )
                return Response(
                    {
                        'detail': 'استان انتخاب‌شده جزو استان‌های قابل ثبت‌نام برای شما نیست.',
                        'wrong_province': True,
                        'class_province': class_province,
                        'member_province': member_province,
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
        member_name = f'{member.user.first_name} {member.user.last_name}'.strip() or member.national_id
        if is_staff_request:
            actor_name, actor_role, _ = actor_info(request.user)
            source_label = f'ثبت‌نام توسط {actor_name} ({actor_role})' if actor_name else 'ثبت‌نام توسط کارمند'
        else:
            source_label = 'ثبت‌نام اینترنتی (خودِ دانش‌پژوه از سایت)'
        record(
            request, 'class', 'class_enroll', f'ثبت‌نام «{member_name}» در «{cls.name}»',
            target_type='کلاس', target_id=str(cls.pk), target_label=cls.name, branch=cls.branch,
            identifier=member.national_id,
            changes=[{'field': 'نحوه‌ی ثبت‌نام', 'old': '', 'new': source_label}],
        )
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
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    # فیلدهایی که «مدرس» اجازه‌ی تغییرشان را دارد (نه جابه‌جا کردن دانش‌پژوه یا کلاس)
    TEACHER_EDITABLE_FIELDS = {'score', 'absent'}

    def get_permissions(self):
        # حذف ثبت‌نام فقط کارکنان؛ بقیه فقط با ورود (دسترسی دقیق در get_queryset و partial_update)
        if self.action == 'destroy':
            return [IsEducationStaff()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if staff_role(user) is not None:
            national_id = self.request.query_params.get('member_national_id')
            membership_code = self.request.query_params.get('member_membership_code')
            if national_id:
                qs = qs.filter(member__national_id=national_id)
            if membership_code:
                qs = qs.filter(member__membership_code=membership_code)
            # مسئول آموزش فقط ثبت‌نام‌های «کلاس‌های شعبه‌ی خودش» را می‌بیند و تغییر می‌دهد
            # (ثبت‌نامی که کلاسش حذف شده، با شعبه‌ی «درس» سنجیده می‌شود)
            own = officer_branch_name(user)
            if own is not None:
                if not own:
                    return qs.none()
                qs = qs.filter(
                    Q(class_obj__branch__in=branch_values(Class, own))
                    | Q(class_obj__isnull=True, lesson__branch__in=branch_values(Lesson, own))
                )
            return qs
        # دانش‌پژوه: فقط ثبت‌نام‌های خودش (پارامترهای کد ملی/کد عضویت نادیده گرفته می‌شوند)
        member = member_of(user)
        if member is not None:
            return qs.filter(member=member)
        # مدرس: فقط ثبت‌نام‌های کلاس‌های خودش
        teacher = teacher_employee(user)
        if teacher is not None:
            return qs.filter(class_obj__teacher=teacher)
        return qs.none()

    def partial_update(self, request, *args, **kwargs):
        # ثبت نمره/غیبت فقط کارکنان و مدرسِ همان کلاس؛ دانش‌پژوه هرگز
        if staff_role(request.user) is None:
            if teacher_employee(request.user) is None:
                return Response({'detail': 'شما اجازه‌ی ویرایش ندارید.'}, status=status.HTTP_403_FORBIDDEN)
            extra = set(request.data.keys()) - self.TEACHER_EDITABLE_FIELDS
            if extra:
                return Response({'detail': 'مدرس فقط نمره و غیبت را می‌تواند تغییر دهد.'}, status=status.HTTP_403_FORBIDDEN)
        return super().partial_update(request, *args, **kwargs)


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


def _log_seminar_rejected(request, seminar, member, reason):
    """رد شدنِ ثبت‌نامِ سمینار، دقیقاً مثل _log_enroll_rejected برای کلاس."""
    name = f'{member.user.first_name} {member.user.last_name}'.strip() or member.national_id
    record_dedup(
        request, 'class', 'seminar_enroll_rejected', f'رد شدن ثبت‌نام «{name}» در سمینار «{seminar.name}»: {reason}',
        status='failed', target_type='سمینار', target_id=str(seminar.pk), target_label=seminar.name,
        branch=seminar.branch, identifier=member.national_id,
    )


@audit('class', 'سمینار/کارگاه', {
    'create': ('seminar_create', 'افزودن سمینار/کارگاه'),
    'update': ('seminar_update', 'ویرایش سمینار/کارگاه'),
    'destroy': ('seminar_delete', 'حذف سمینار/کارگاه'),
})
class SeminarViewSet(AuditedMixin, OfficerBranchWriteMixin, viewsets.ModelViewSet):
    """
    مدیریت سمینار/کارگاه + ثبت‌نامِ دانش‌پژوه در آن (اکشنِ enroll، دقیقاً هم‌خانواده‌ی
    enroll کلاس، ولی بدون رده‌سنی/پیش‌نیاز - که مفهومِ سمینار نیستند).
    """
    queryset = Seminar.objects.select_related('department', 'lesson', 'teacher', 'term').prefetch_related('sessions')
    serializer_class = SeminarSerializer
    permission_classes = [ReadOnlyOrEducationStaff]

    def get_permissions(self):
        # مثل کلاس: ثبت‌نام عمومی (با تأیید هویت)، لیست دانش‌پژوهان فقط با ورود و بررسی دقیق داخل action
        if self.action == 'enroll':
            return [permissions.AllowAny()]
        if self.action == 'students':
            return [permissions.IsAuthenticated()]
        return [ReadOnlyOrEducationStaff()]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        branch = params.get('branch')
        if branch:
            qs = qs.filter(branch=branch)
        term = params.get('term')
        if term:
            qs = qs.filter(term_id=term)
        class_type = params.get('class_type')
        if class_type:
            qs = qs.filter(class_type=class_type)
        published = params.get('published')
        if published is not None:
            qs = qs.filter(is_published=published.lower() in ('1', 'true', 'yes'))
        return qs

    @action(detail=True, methods=['get'])
    def students(self, request, pk=None):
        seminar = self.get_object()
        teacher = teacher_employee(request.user)
        own = officer_branch_name(request.user)
        is_manager = staff_role(request.user) is not None and own is None
        is_officer_of_branch = own is not None and same_branch(seminar.branch, own)
        is_seminar_teacher = teacher is not None and seminar.teacher_id == teacher.id
        if not (is_manager or is_officer_of_branch or is_seminar_teacher):
            return Response({'detail': 'شما به لیست شرکت‌کنندگان این سمینار دسترسی ندارید.'}, status=status.HTTP_403_FORBIDDEN)
        enrollments = seminar.enrollments.select_related('member', 'member__user').all()
        return Response(SeminarEnrollmentSerializer(enrollments, many=True).data)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        seminar = self.get_object()
        is_staff_request = staff_role(request.user) is not None

        if not is_staff_request and not SiteSettings.load().public_registration_enabled:
            return Response(
                {'detail': 'در حال حاضر ثبت‌نام در سمینارها و کارگاه‌ها برای عموم بسته است.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        national_id = (request.data.get('national_id') or '').strip()
        membership_code = (request.data.get('membership_code') or '').strip()
        if not national_id or not membership_code:
            return Response({'detail': 'کد ملی و کد عضویت لازم است.'}, status=status.HTTP_400_BAD_REQUEST)

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
            response = throttle.fail(request, ctx, 'identity_failed', 'تلاش ناموفق برای تأیید هویت هنگام ثبت‌نام سمینار (کد ملی و کد عضویت نخواند)',
                                     not_found, status.HTTP_400_BAD_REQUEST)
            if response.status_code == status.HTTP_400_BAD_REQUEST:
                response.data['is_member'] = False
            return response
        if ctx is not None:
            throttle.register_success(ctx['key'])
        if hasattr(member, 'ban'):
            _log_seminar_rejected(request, seminar, member, 'عضو محروم است')
            return Response(
                {'is_member': True, 'is_banned': True, 'ban_reason': member.ban.reason, 'detail': 'این عضو محروم شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not member.is_membership_valid:
            _log_seminar_rejected(request, seminar, member, 'عضویت منقضی شده است')
            return Response(
                {'is_member': True, 'is_valid': False, 'detail': 'عضویت این فرد منقضی شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # همان قاعده‌ی استانِ کلاس‌های مجازی: فقط اگر سراسری نباشد، و فقط وقتی
        # استانِ هم سمینار و هم دانش‌پژوه مشخص باشد
        if not seminar.is_national:
            from core.models import Branch

            canonical_seminar_branch = canonical_branch_name(seminar.branch) or (seminar.branch or '').strip()
            seminar_branch = Branch.objects.filter(name=canonical_seminar_branch).first()
            seminar_province = (seminar_branch.province if seminar_branch else '') or ''
            member_province = (member.province or '').strip()
            if seminar_province and member_province and seminar_province != member_province:
                _log_seminar_rejected(
                    request, seminar, member,
                    f'استان سمینار ({seminar_province}) با استان دانش‌پژوه ({member_province}) نمی‌خواند',
                )
                return Response(
                    {
                        'detail': 'استان انتخاب‌شده جزو استان‌های قابل ثبت‌نام برای شما نیست.',
                        'wrong_province': True,
                        'class_province': seminar_province,
                        'member_province': member_province,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if seminar.is_full:
            _log_seminar_rejected(request, seminar, member, 'ظرفیت سمینار تکمیل است')
            return Response({'detail': 'ظرفیت این سمینار/کارگاه تکمیل شده است.'}, status=status.HTTP_400_BAD_REQUEST)
        if SeminarEnrollment.objects.filter(seminar=seminar, member=member).exists():
            _log_seminar_rejected(request, seminar, member, 'قبلاً در این سمینار ثبت‌نام کرده است')
            return Response(
                {'detail': 'قبلاً در این سمینار/کارگاه ثبت‌نام کرده‌اید.', 'already_enrolled': True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment = SeminarEnrollment.objects.create(seminar=seminar, member=member)
        member_name = f'{member.user.first_name} {member.user.last_name}'.strip() or member.national_id
        if is_staff_request:
            actor_name, actor_role, _ = actor_info(request.user)
            source_label = f'ثبت‌نام توسط {actor_name} ({actor_role})' if actor_name else 'ثبت‌نام توسط کارمند'
        else:
            source_label = 'ثبت‌نام اینترنتی (خودِ دانش‌پژوه از سایت)'
        record(
            request, 'class', 'seminar_enroll', f'ثبت‌نام «{member_name}» در سمینار «{seminar.name}»',
            target_type='سمینار', target_id=str(seminar.pk), target_label=seminar.name, branch=seminar.branch,
            identifier=member.national_id,
            changes=[{'field': 'نحوه‌ی ثبت‌نام', 'old': '', 'new': source_label}],
        )
        return Response(SeminarEnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)


# ============================ مدیریت اسلاید شو ============================

@audit('settings', 'اسلاید', {
    'create': ('slide_create', 'افزودن اسلاید'),
    'update': ('slide_update', 'ویرایش اسلاید'),
    'destroy': ('slide_delete', 'حذف اسلاید'),
}, label_func=lambda s: s.title or f'اسلاید {s.pk}', skip_fields=('image', 'mobile_image'))
class SlideViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    مدیریت اسلایدهای صفحه‌ی اصلی - فقط «مدیر آموزش».
    ترتیب با اکشن reorder (کشیدن و رها کردن در پنل) و کپی با duplicate انجام می‌شود.
    """
    queryset = Slide.objects.all()
    serializer_class = SlideSerializer
    permission_classes = [IsEducationManager]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def perform_create(self, serializer):
        # اسلاید جدید همیشه آخرِ لیست قرار می‌گیرد
        last = Slide.objects.order_by('-order').first()
        serializer.save(order=(last.order + 1) if last else 0)

    def perform_update(self, serializer):
        # با عوض شدن تصویر، فایل قبلی از روی دیسک پاک می‌شود
        old = serializer.instance
        old_files = {'image': old.image.name if old.image else None,
                     'mobile_image': old.mobile_image.name if old.mobile_image else None}
        super().perform_update(serializer)
        new = serializer.instance
        for field, name in old_files.items():
            f = getattr(new, field)
            if name and (not f or f.name != name):
                old.__class__._meta.get_field(field).storage.delete(name)

    def perform_destroy(self, instance):
        files = [f for f in (instance.image, instance.mobile_image) if f]
        names = [(f.storage, f.name) for f in files]
        super().perform_destroy(instance)
        for storage, name in names:
            storage.delete(name)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """بدنه: {"ids": [3,1,2]} - ترتیب جدید همه‌ی اسلایدها."""
        ids = request.data.get('ids')
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response({'detail': 'فهرست شناسه‌ها نامعتبر است.'}, status=400)
        existing = set(Slide.objects.values_list('id', flat=True))
        if set(ids) != existing or len(ids) != len(existing):
            return Response({'detail': 'فهرست باید شامل همه‌ی اسلایدها باشد؛ صفحه را تازه کنید.'}, status=400)
        with transaction.atomic():
            for pos, sid in enumerate(ids):
                Slide.objects.filter(pk=sid).update(order=pos)
        record(request, 'settings', 'slide_reorder', 'تغییر ترتیب اسلایدها', target_type='اسلاید')
        return Response({'ok': True})

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        from django.core.files.base import ContentFile
        src = self.get_object()
        last = Slide.objects.order_by('-order').first()
        copy = Slide(
            title=(src.title + ' (کپی)')[:120], subtitle=src.subtitle, alt_text=src.alt_text,
            button_text=src.button_text, link_url=src.link_url, open_new_tab=src.open_new_tab,
            text_position=src.text_position, text_color=src.text_color, overlay=src.overlay,
            is_active=False, start_at=src.start_at, end_at=src.end_at, order=(last.order + 1) if last else 0,
        )
        for field in ('image', 'mobile_image'):
            f = getattr(src, field)
            if f:
                with f.open('rb') as fh:
                    getattr(copy, field).save(f.name.rsplit('/', 1)[-1], ContentFile(fh.read()), save=False)
        copy.save()
        record(request, 'settings', 'slide_create', 'کپی اسلاید', target_type='اسلاید', target_label=copy.title)
        return Response(SlideSerializer(copy, context={'request': request}).data, status=201)


class SlideSettingsView(APIView):
    """تنظیمات سراسری اسلاید شو (پخش خودکار، مدت، افکت...) - فقط مدیر آموزش."""
    permission_classes = [IsEducationManager]

    def get(self, request):
        return Response(SlideSettingsSerializer(SiteSettings.load()).data)

    def patch(self, request):
        obj = SiteSettings.load()
        ser = SlideSettingsSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        record(request, 'settings', 'slide_settings', 'تغییر تنظیمات اسلاید شو', target_type='تنظیمات')
        return Response(ser.data)


class PublicSlidesView(APIView):
    """اسلایدهای فعالِ همین لحظه برای صفحه‌ی اصلی (عمومی، فقط خواندنی)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.utils import timezone
        now = timezone.now()
        slides = [s for s in Slide.objects.filter(is_active=True) if s.status(now) == 'live']
        cfg = SlideSettingsSerializer(SiteSettings.load()).data

        def url(f):
            return request.build_absolute_uri(f.url) if f else None
        resp = Response({
            'settings': cfg,
            'slides': [{
                'id': s.id, 'title': s.title, 'subtitle': s.subtitle, 'image': url(s.image),
                'mobile_image': url(s.mobile_image), 'alt': s.alt_text or s.title,
                'button_text': s.button_text, 'link_url': s.link_url, 'new_tab': s.open_new_tab,
                'position': s.text_position, 'color': s.text_color, 'overlay': s.overlay,
            } for s in slides],
        })
        resp['Cache-Control'] = 'no-cache'
        return resp


class RulesView(APIView):
    """
    متن «قوانین و مقررات» سایت. خواندن عمومی است (صفحه‌ی /rules)؛ ویرایش فقط مدیر آموزش.
    """
    permission_classes = [ReadOnlyOrEducationManager]
    MAX_LEN = 30000

    def _data(self, obj):
        # تا وقتی هیچ‌بار ویرایش نشده، متن پیش‌فرض نمایش داده می‌شود
        from .default_rules import DEFAULT_RULES
        text = obj.rules_text if obj.rules_updated_at else DEFAULT_RULES
        return {'text': text, 'updated_at': obj.rules_updated_at, 'is_default': not obj.rules_updated_at}

    def get(self, request):
        return Response(self._data(SiteSettings.load()))

    def patch(self, request):
        text = request.data.get('text')
        if not isinstance(text, str):
            return Response({'detail': 'متن قوانین نامعتبر است.'}, status=400)
        text = text.replace('\r\n', '\n').strip()
        if len(text) > self.MAX_LEN:
            return Response({'detail': f'متن قوانین نباید بیشتر از {self.MAX_LEN} نویسه باشد.'}, status=400)
        from django.utils import timezone
        obj = SiteSettings.load()
        obj.rules_text = text
        obj.rules_updated_at = timezone.now()
        obj.save(update_fields=['rules_text', 'rules_updated_at'])
        record(request, 'settings', 'rules_update', 'ویرایش قوانین و مقررات', target_type='تنظیمات')
        return Response(self._data(obj))


@audit('settings', 'اطلاعیه', {
    'create': ('announcement_create', 'افزودن اطلاعیه'),
    'update': ('announcement_update', 'ویرایش اطلاعیه'),
    'destroy': ('announcement_delete', 'حذف اطلاعیه'),
}, label_func=lambda a: a.title, branch_func=lambda a: a.branch)
class AnnouncementViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    مدیریت اطلاعیه‌ها. مدیر آموزش: همه؛ مسئول آموزش: اطلاعیه‌های شعبه‌ی خودش را می‌سازد/ویرایش می‌کند
    (اطلاعیه‌های «همه‌ی شعب» را فقط می‌بیند).
    """
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementSerializer
    permission_classes = [IsEducationStaff]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        own = officer_branch_name(self.request.user)
        if own is not None:
            qs = qs.filter(Q(branch=own) | Q(branch=''))
        return qs

    def _own_or_403(self, obj_branch):
        own = officer_branch_name(self.request.user)
        if own is not None and not same_branch(obj_branch, own):
            raise PermissionDenied('شما فقط اطلاعیه‌های شعبه‌ی خودتان را می‌توانید مدیریت کنید.')

    def perform_create(self, serializer):
        own = officer_branch_name(self.request.user)
        if own is not None:
            serializer.save(branch=own)   # مسئول آموزش: همیشه شعبه‌ی خودش
        else:
            serializer.save()

    def perform_update(self, serializer):
        own = officer_branch_name(self.request.user)
        self._own_or_403(serializer.instance.branch)
        if own is not None:
            serializer.save(branch=own)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        self._own_or_403(instance.branch)
        super().perform_destroy(instance)


class PublicAnnouncementsView(APIView):
    """
    اطلاعیه‌های صفحه‌ی لیست کلاس‌ها: ?branch=<نام شعبه> → اطلاعیه‌های همان شعبه + «همه‌ی شعب».
    بدون branch فقط اطلاعیه‌های «همه‌ی شعب». عمومی و فقط خواندنی.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        branch = canonical_branch_name(request.query_params.get('branch', ''))
        qs = Announcement.objects.filter(Q(branch='') | Q(branch=branch)) if branch else Announcement.objects.filter(branch='')
        return Response([
            {'id': a.id, 'title': a.title, 'text': a.text, 'date': a.jalali_date, 'branch': a.branch}
            for a in qs[:50]
        ])
