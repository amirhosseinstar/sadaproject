# ===== مسیر این فایل در پروژه: core/views.py (کنار manage.py) =====
"""
API نیروی انسانی، شعب و متقاضیان تدریس.

  GET/POST         /api/core/branches/       -> لیست شعب (خواندن برای همه، نوشتن فقط ادمین)
  GET/PUT/DELETE    /api/core/branches/<id>/  -> جزئیات یک شعبه

  GET               /api/core/employees/      -> نیروی انسانی (فقط خواندن از این مسیر؛
                                                   تنها راه ساخته شدن یک «مدرس» تأیید
                                                   درخواستش در teacher-applicants است)
  GET/PUT/DELETE     /api/core/employees/<id>/

  POST                       /api/core/teacher-applicants/          -> ثبت درخواست همکاری (برای همه، حتی بدون ورود)
  GET/DELETE                 /api/core/teacher-applicants/<id>/     -> مشاهده/حذف یک درخواست (پنل ادمین)
  POST                       /api/core/teacher-applicants/<id>/approve/  -> تأیید درخواست؛ همین‌جا یک Employee واقعی ساخته می‌شود
"""

import re

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db import transaction
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from .models import Branch, Employee, TeacherApplicant
from .serializers import BranchSerializer, EmployeeSerializer, StaffSerializer, TeacherApplicantSerializer
from core.permissions import (
    ROLE_MANAGER, ROLE_OFFICER, ROLE_TEACHER, STAFF_ROLES, IsEducationManager, IsEducationStaff,
    ReadOnlyOrEducationManager, officer_branch_name, same_branch, scope_to_officer_branch, staff_role,
)
from logs.mixins import AuditedMixin, audit
from .services import ApprovalError, approve_teacher_applicant, ensure_username_available
from logs.recorder import record

User = get_user_model()



@audit('settings', 'شعبه', {
    'create': ('branch_create', 'افزودن شعبه'),
    'update': ('branch_update', 'ویرایش شعبه'),
    'destroy': ('branch_delete', 'حذف شعبه'),
}, branch_field='name')
class BranchViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    لیست شعب داده‌ی عمومی است (سایت اصلی و فرم ثبت‌نام مدرس آن را می‌خوانند)، ولی
    افزودن/ویرایش/حذف شعبه فقط برای «مدیر آموزش» است (مسئول آموزش فقط می‌خواند).
    """
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [ReadOnlyOrEducationManager]


@audit('teacher', 'مدرس', {
    'update': ('teacher_update', 'ویرایش اطلاعات مدرس'),
    'destroy': ('teacher_delete', 'حذف مدرس'),
})
class EmployeeViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    عمداً فقط GET/PUT/PATCH/DELETE کاربردی است (create از طریق این مسیر معنی
    ندارد): تنها راه ساخته شدن یک نیروی «مدرس» تازه، تأیید درخواستش در
    TeacherApplicantViewSet.approve است - همان‌جایی که هم‌زمان حساب ورودش
    هم ساخته می‌شود. این محدودیت را http_method_names تضمین می‌کند.

    امنیت:
      - فقط مدیر/مسئول آموزش (اطلاعات مدرسین شخصی است: کد ملی، تلفن، آدرس، عکس).
      - این مسیر فقط روی نیروهای با سمت «مدرس» کار می‌کند؛ مدیر/مسئول فقط از مسیر staff
        (مخصوص مدیر آموزش) ساخته/ویرایش می‌شوند.
      - «سمت» از این مسیر قابل تغییر نیست (read_only در سریالایزر) تا کسی نتواند یک مدرس را مدیر کند.
      - مسئول آموزش فقط مدرسین شعبه‌ی خودش را می‌بیند/ویرایش/حذف می‌کند و نمی‌تواند شعبه‌ی مدرس را عوض کند.
    """
    queryset = Employee.objects.filter(role=ROLE_TEACHER)
    serializer_class = EmployeeSerializer
    permission_classes = [IsEducationStaff]
    http_method_names = ['get', 'put', 'patch', 'delete', 'head', 'options']

    def perform_destroy(self, instance):
        # نکته‌ی مهم: Employee.user با on_delete=SET_NULL تعریف شده که فقط
        # جهت عکس رو مدیریت می‌کنه (اگر User حذف بشه، Employee.user خالی
        # می‌شود) - ولی برعکسش را جنگو خودکار انجام نمی‌دهد: حذف یک
        # Employee به‌خودی‌خود حساب User وصل‌شده را حذف نمی‌کند. نتیجه‌اش
        # این بود که نام‌کاربری یک مدرسِ حذف‌شده برای همیشه «قبلاً استفاده
        # شده» می‌ماند و دیگر هیچ‌وقت قابل استفاده‌ی دوباره نبود. برای همین
        # این‌جا صریحاً حساب کاربری مرتبط را هم حذف می‌کنیم.
        user = instance.user
        instance.delete()
        if user is not None:
            user.delete()

    def get_queryset(self):
        qs = scope_to_officer_branch(super().get_queryset(), self.request.user)
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)
        return qs

    def perform_update(self, serializer):
        # مسئول آموزش نمی‌تواند مدرس را به شعبه‌ی دیگری منتقل کند
        if staff_role(self.request.user) == ROLE_OFFICER:
            serializer.validated_data.pop('branch', None)

        # نام‌کاربری و رمز «حساب ورودِ» مدرس (مدل User) فیلد خودِ Employee نیستند؛ سریالایزر آن‌ها را
        # نمی‌شناسد و قبلاً بی‌صدا نادیده گرفته می‌شد (فرم می‌گفت ذخیره شد ولی چیزی عوض نمی‌شد).
        # اینجا صریحاً از بدنه‌ی درخواست خوانده و روی User اعمال می‌شود. همه‌ی بررسی‌ها قبل از هر
        # ذخیره‌سازی انجام می‌شود تا خطا، نیمه‌کاره‌ماندن تغییرات را نسازد.
        username = (self.request.data.get('username') or '').strip()
        password = self.request.data.get('password') or ''
        instance = serializer.instance
        user = instance.user

        if password:
            _ensure_password_strength_or_400(password)
        username_changed = bool(username) and (user is None or username != user.username)
        if username_changed:
            _ensure_username_format_or_400(username)
            _ensure_username_or_400(username, exclude_user_pk=user.pk if user else None)
        if user is None and username and not password:
            raise serializers.ValidationError({'detail': 'این مدرس هنوز حساب ورود ندارد؛ برای ساخت آن، رمز عبور را هم وارد کنید.'})

        with transaction.atomic():
            if user is not None:
                if username_changed:
                    user.username = username
                if password:
                    user.set_password(password)
                if username_changed or password:
                    user.save()
                serializer.save()
            elif username and password:
                # مدرسِ قدیمی که حساب ورود نداشت: همین‌جا حسابش ساخته می‌شود
                serializer.save(user=User.objects.create_user(username=username, password=password))
            else:
                serializer.save()


def _ensure_username_format_or_400(username):
    """نام‌کاربری فقط حروف/رقم انگلیسی و . _ - (هم‌سان با MyProfileView)؛ فاصله و حروف فارسی رد می‌شود."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
        raise serializers.ValidationError({'detail': 'نام کاربری فقط می‌تواند شامل حروف/رقم انگلیسی و . _ - باشد.'})


def _ensure_username_or_400(username, exclude_user_pk=None):
    """ensure_username_available را صدا می‌زند و خطایش را به پاسخ ۴۰۰ API تبدیل می‌کند."""
    try:
        ensure_username_available(username, exclude_user_pk=exclude_user_pk)
    except ApprovalError as e:
        raise serializers.ValidationError({'detail': str(e)})


def _ensure_password_strength_or_400(password):
    """حداقل طول رمز عبور (هم‌سان با ویرایش پروفایل خود کاربر: ۶ کاراکتر)."""
    if len(password) < 6:
        raise serializers.ValidationError({'detail': 'رمز عبور باید حداقل ۶ کاراکتر باشد.'})


def _manager_count():
    """تعداد حساب‌های «مدیر آموزش» که واقعاً می‌توانند وارد پنل شوند (دارای حساب کاربری)."""
    return Employee.objects.filter(role=ROLE_MANAGER, user__isnull=False).count()


@audit('staff', 'مدیر/مسئول آموزش', {
    'create': ('staff_create', 'ساخت حساب مدیر/مسئول آموزش'),
    'update': ('staff_update', 'ویرایش اطلاعات مدیر/مسئول آموزش'),
    'destroy': ('staff_delete', 'حذف مدیر/مسئول آموزش'),
})
class StaffViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    متصدیان (مدیر آموزش/مسئول آموزش) - بر خلاف EmployeeViewSet (که فقط
    خواندنی است چون مدرس فقط از تأیید درخواست ساخته می‌شود)، اینجا
    افزودن/ویرایش/حذف مستقیم مجاز است؛ این تنها راه ساخته‌شدن یک متصدی
    است - از پنل ادمین جنگو دیگر نمی‌شود متصدی ساخت.

    امنیت: فقط «مدیر آموزش» (ساختنِ حساب مدیر/مسئول = بالاترین سطح دسترسی است).
    قفل‌های جلوگیری از حذف/تنزل حساب خود و آخرین مدیر هم در perform_destroy/perform_update است.
    """
    queryset = Employee.objects.filter(role__in=['مدیر آموزش', 'مسئول آموزش'])
    serializer_class = StaffSerializer
    permission_classes = [IsEducationManager]

    def get_queryset(self):
        qs = Employee.objects.filter(role__in=['مدیر آموزش', 'مسئول آموزش'])
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def perform_create(self, serializer):
        username = (serializer.validated_data.pop('username', '') or '').strip()
        password = serializer.validated_data.pop('password', '') or ''
        if not username or not password:
            raise serializers.ValidationError({'detail': 'نام‌کاربری و رمز عبور برای متصدی جدید الزامی است.'})
        _ensure_password_strength_or_400(password)
        _ensure_username_format_or_400(username)
        _ensure_username_or_400(username)
        user = User.objects.create_user(username=username, password=password)
        serializer.save(user=user)

    def perform_destroy(self, instance):
        # حذف حساب خود یا آخرین مدیر آموزش، سامانه را بدون مدیر (قفل‌شده) می‌گذارد
        if instance.user_id is not None and instance.user_id == self.request.user.pk:
            raise serializers.ValidationError({'detail': 'نمی‌توانید حساب کاربری خودتان را حذف کنید.'})
        if instance.role == ROLE_MANAGER and _manager_count() <= 1:
            raise serializers.ValidationError({'detail': 'آخرین مدیر آموزش قابل حذف نیست.'})
        # مثل EmployeeViewSet.perform_destroy: حذف متصدی به‌تنهایی حساب User وصل‌شده را
        # حذف نمی‌کند و نام کاربری برای همیشه قفل می‌ماند. حساب مدیر سیستم
        # (superuser) هیچ‌وقت حذف نمی‌شود.
        user = instance.user
        instance.delete()
        if user is not None and not user.is_superuser and not user.is_staff:
            user.delete()

    def perform_update(self, serializer):
        username = (serializer.validated_data.pop('username', '') or '').strip()
        password = serializer.validated_data.pop('password', '') or ''
        instance = serializer.instance

        # آخرین مدیر آموزش نباید به «مسئول آموزش» تنزل پیدا کند
        new_role = serializer.validated_data.get('role', instance.role)
        if instance.role == ROLE_MANAGER and new_role != ROLE_MANAGER and _manager_count() <= 1:
            raise serializers.ValidationError({'detail': 'آخرین مدیر آموزش را نمی‌شود به مسئول آموزش تغییر داد.'})
        if password:
            _ensure_password_strength_or_400(password)

        if instance.user:
            if username and username != instance.user.username:
                _ensure_username_format_or_400(username)
                _ensure_username_or_400(username, exclude_user_pk=instance.user.pk)
                instance.user.username = username
            if password:
                instance.user.set_password(password)
            instance.user.save()
        elif username and password:
            _ensure_username_or_400(username)
            user = User.objects.create_user(username=username, password=password)
            serializer.save(user=user)
            return

        serializer.save()


@audit('teacher', 'درخواست همکاری مدرس', {
    'create': ('applicant_create', 'ثبت درخواست همکاری مدرس (فرم عمومی)'),
    'update': ('applicant_update', 'ویرایش درخواست همکاری مدرس'),
    'destroy': ('applicant_delete', 'حذف درخواست همکاری مدرس'),
    'approve': ('applicant_approve', 'تأیید درخواست همکاری مدرس و ساخت حساب'),
})
class ApplicantSubmitThrottle(SimpleRateThrottle):
    """
    محدودیت ثبت درخواست همکاریِ «عمومی» (بدون ورود): ۲۰ مورد در ساعت برای هر IP، تا نشود با
    فرم عمومی (که فایل تا ۵ مگابایت می‌گیرد) دیسک و پنل را پر کرد. فقط ثبتِ ناشناس را محدود
    می‌کند؛ ثبت دستی توسط مدیر/مسئولِ واردشده معاف است.
    """
    scope = 'applicant_submit'
    rate = '20/hour'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class TeacherApplicantViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    امنیت:
      - ثبت درخواست (POST) برای همه باز است (فرم عمومی teacher-registration.html) ولی محدودیت تعداد دارد.
      - مشاهده/ویرایش/حذف/تأیید فقط برای مدیر/مسئول آموزش است (رکوردها اطلاعات شخصی متقاضیان
        را دارند: تلفن، کد ملی، آدرس، عکس، رزومه).
      - مسئول آموزش فقط درخواست‌های شعبه‌ی خودش را می‌بیند و درخواستی که خودش ثبت می‌کند همیشه
        به شعبه‌ی خودش نسبت داده می‌شود.
    """
    queryset = TeacherApplicant.objects.all()
    serializer_class = TeacherApplicantSerializer
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.AllowAny()]
        return [IsEducationStaff()]

    def get_throttles(self):
        if self.action == 'create' and staff_role(self.request.user) is None:
            return [ApplicantSubmitThrottle()]
        return []

    def perform_create(self, serializer):
        own = officer_branch_name(self.request.user)
        if own:
            serializer.save(branch=own)
        else:
            serializer.save()

    def get_queryset(self):
        qs = scope_to_officer_branch(super().get_queryset(), self.request.user)
        if self.action == 'list':
            # فهرست «مدرسین متقاضی» فقط درخواست‌های در انتظار بررسی را نشان
            # می‌دهد؛ درخواست‌های تأییدشده از اینجا محو می‌شوند و در فهرست
            # «مدرسین تأییدشده» (core/employees) دیده می‌شوند.
            qs = qs.filter(status=TeacherApplicant.STATUS_PENDING)
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        applicant = self.get_object()
        username = request.data.get('username')
        password = request.data.get('password')
        try:
            employee = approve_teacher_applicant(applicant, username, password)
        except ApprovalError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'applicant': self.get_serializer(applicant).data,
            'employee': EmployeeSerializer(employee, context=self.get_serializer_context()).data,
        })


class MyProfileView(APIView):
    """
    ویرایش «اطلاعات حساب خودِ» مدیر آموزش یا مسئول آموزشِ واردشده (نه هیچ‌کس دیگر؛ همیشه
    از روی request.user.employee عمل می‌کند، نه از روی id در آدرس یا بدنه‌ی درخواست).

      GET    /api/core/my-profile/   -> نام، تلفن، نام کاربری، سمت، شعبه‌ی خودِ کاربر
      PATCH  /api/core/my-profile/   -> ویرایش نام/تلفن/نام کاربری/رمز عبور (هرکدام اختیاری)

    سمت (role) و شعبه از این مسیر هرگز قابل‌تغییر نیستند؛ حتی اگر در بدنه‌ی درخواست
    فرستاده شوند نادیده گرفته می‌شوند - جلوگیری از ترفیع/جابه‌جاییِ خودسرانه.
    """
    permission_classes = [IsEducationStaff]

    def _employee(self, request):
        employee = getattr(request.user, 'employee', None)
        if employee is None or employee.role not in STAFF_ROLES:
            return None
        return employee

    def get(self, request):
        employee = self._employee(request)
        if employee is None:
            return Response({'detail': 'حساب شما به نیروی انسانی وصل نیست.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'name': employee.name, 'phone': employee.phone, 'username': employee.user.username,
            'role': employee.role, 'branch': employee.branch,
        })

    def patch(self, request):
        employee = self._employee(request)
        if employee is None:
            return Response({'detail': 'حساب شما به نیروی انسانی وصل نیست.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        changes = []

        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                return Response({'detail': 'نام و نام‌خانوادگی نمی‌تواند خالی باشد.'}, status=status.HTTP_400_BAD_REQUEST)
            if name != employee.name:
                changes.append({'field': 'نام و نام‌خانوادگی', 'old': employee.name, 'new': name})
                employee.name = name

        if 'phone' in data:
            phone = (data.get('phone') or '').strip()
            if not phone:
                return Response({'detail': 'شماره تماس نمی‌تواند خالی باشد.'}, status=status.HTTP_400_BAD_REQUEST)
            if not re.fullmatch(r'0\d{10}', phone):
                return Response({'detail': 'شماره تماس باید ۱۱ رقم و با صفر شروع شود.'}, status=status.HTTP_400_BAD_REQUEST)
            if phone != employee.phone:
                changes.append({'field': 'شماره تماس', 'old': employee.phone, 'new': phone})
                employee.phone = phone

        username = (data.get('username') or '').strip()
        if username and username != employee.user.username:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
                return Response({'detail': 'نام کاربری فقط می‌تواند شامل حروف/رقم انگلیسی و . _ - باشد.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                ensure_username_available(username, exclude_user_pk=employee.user_id)
            except ApprovalError as error:
                return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)
            changes.append({'field': 'نام کاربری', 'old': employee.user.username, 'new': username})
            employee.user.username = username

        password = data.get('password') or ''
        password_changed = False
        if password:
            if len(password) < 6:
                return Response({'detail': 'رمز عبور باید حداقل ۶ کاراکتر باشد.'}, status=status.HTTP_400_BAD_REQUEST)
            employee.user.set_password(password)
            password_changed = True
            changes.append({'field': 'رمز عبور', 'old': '', 'new': 'تغییر کرد'})

        if not changes:
            return Response({'detail': 'تغییری برای ذخیره وجود ندارد.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            employee.save()
            employee.user.save()
            # اگر رمز عوض شده، نشست فعلی را دست‌نخورده نگه می‌داریم تا کاربر همین لحظه از پنل بیرون نیفتد
            if password_changed:
                update_session_auth_hash(request, employee.user)

        record(request, 'staff', 'self_profile_update', f'ویرایش اطلاعات حساب خود: {employee.name}',
               target_type='حساب', target_label=employee.name, branch=employee.branch, changes=changes)
        return Response({
            'name': employee.name, 'phone': employee.phone, 'username': employee.user.username,
            'role': employee.role, 'branch': employee.branch,
        })
