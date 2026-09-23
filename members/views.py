# ===== مسیر این فایل در پروژه: members/views.py (کنار manage.py) =====
"""
API احراز هویت و مدیریت اعضا.

  POST /api/auth/login/                    -> ورود (با کد ملی + رمز عبور)
  POST /api/auth/logout/                   -> خروج
  GET  /api/auth/me/                       -> اطلاعات کاربر لاگین‌شده‌ی فعلی (برای نوبار سایت)

  POST /api/auth/forgot-password/request/  -> مرحله‌ی ۱ فراموشی رمز: کد ملی -> پیامک کد بازیابی
  POST /api/auth/forgot-password/confirm/  -> مرحله‌ی ۲ فراموشی رمز: کد + رمز جدید
  POST /api/auth/otp-login/request/        -> مرحله‌ی ۱ ورود با رمز یکبارمصرف: کد ملی -> پیامک کد ورود
  POST /api/auth/otp-login/verify/         -> مرحله‌ی ۲ ورود با رمز یکبارمصرف: کد -> ورود واقعی

  GET   /api/members/?national_id=..&membership_code=..&first_name=..&last_name=..
                                            -> جستجوی اعضا (صفحه‌ی «اعضا» در پنل ادمین)
                                               وضعیت عضویت (is_membership_valid) خودکار
                                               از روی card_expires_at محاسبه می‌شود.
  POST  /api/members/<id>/ban/             -> محروم کردن عضو (بدنه: reason اختیاری)
  POST  /api/members/<id>/unban/           -> رفع محرومیت

  POST  /api/members/verify/               -> بررسی «آیا این فرد می‌تواند ثبت‌نام کند؟»
                                               (بدنه: national_id, membership_code)
                                               برای هم افزودن دستی دانش‌پژوه در پنل ادمین
                                               و هم ویزارد ثبت‌نام دوره در سایت اصلی

نکته برای یادگیری: این APIها بر پایه‌ی «session» کار می‌کنند، یعنی بعد از
لاگین موفق، جنگو یک کوکی امن در مرورگر کاربر می‌سازد و در درخواست‌های بعدی
همان کوکی فرستاده می‌شود تا معلوم شود کاربر کیست. فرانت‌اند لازم نیست
خودش چیزی در localStorage نگه دارد؛ فقط کافی‌ست fetch() را با
credentials: 'include' صدا بزند.
"""

import random

from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Member, MemberBan, OTPCode, EmployeeOTPCode
from .serializers import MemberSearchSerializer, MemberUpdateSerializer, build_profile_payload
from .sms import send_sms
from core.models import Employee
from core.permissions import IsEducationStaff
from logs import throttle
from logs.mixins import AuditedMixin, audit
from logs.models import AuditLog
from logs.recorder import actor_info as record_actor
from logs.recorder import record

# کد چند دقیقه معتبر است - بعد از این مدت باید دوباره درخواست کد جدید بدهید
OTP_VALID_MINUTES = 5


@method_decorator(ensure_csrf_cookie, name='get')
class CsrfView(APIView):
    """
    این مسیر فقط یک کار می‌کند: کوکی csrftoken را در مرورگر کاربر می‌سازد.
    فرانت‌اند باید یک‌بار (مثلاً موقع بار شدن صفحه) این را صدا بزند، بعد
    مقدار کوکی csrftoken را در هدر X-CSRFToken برای درخواست‌های POST بعدی
    (مثل logout یا ثبت‌نام دوره) بفرستد. این یک تدبیر امنیتی استاندارد
    جنگو است تا سایت دیگری نتواند بدون اجازه‌ی کاربر برایش درخواست بفرستد.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'detail': 'csrf cookie set'})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = request.data.get('password') or ''
        # login_type اختیاری است: اگر فرانت بفرستد ('student' یا 'teacher')،
        # مطمئن می‌شویم حساب واردشده واقعاً همان نوع است (مثلاً یک دانش‌پژوه
        # نتواند از صفحه‌ی ورود مدرسین وارد شود و برعکس). اگر فرستاده نشود
        # (برای سازگاری با کدهای قدیمی‌تر)، این بررسی انجام نمی‌شود.
        login_type = (request.data.get('login_type') or '').strip()

        if not username or not password:
            return Response(
                {'detail': 'نام کاربری و گذرواژه را وارد کنید.'},
                status=400,
            )

        # قفل موقت: اگر این حساب به‌خاطر تلاش‌های ناموفق زیاد مسدود است، اصلاً رمز بررسی نمی‌شود
        ctx, blocked = throttle.guard(username)
        if blocked:
            return blocked

        user = authenticate(request, username=username, password=password)
        if user is None:
            # پیام یکسان برای هر دو حالت («کاربر وجود ندارد» یا «رمز اشتباه است»):
            # این یک تدبیر امنیتی استاندارد است، چون اگر پیام‌ها فرق کنند، هرکسی
            # می‌تواند با امتحان کردن کدهای مختلف بفهمد کدام کد ملی/عضویت اصلاً
            # در سامانه ثبت شده - حتی بدون این‌که رمزش را بداند.
            # (تلاش ناموفق شمرده و در لاگ ثبت می‌شود؛ بعد از چند تلاش هشدار و سپس مسدودی)
            return throttle.fail(
                request, ctx, 'login_failed', 'تلاش ناموفق برای ورود (نام کاربری یا گذرواژه اشتباه)',
                'ورود ناموفق بود؛ نام کاربری یا گذرواژه را بررسی کنید.', 401,
            )

        payload = build_profile_payload(user)

        def wrong_type(message, reason):
            # رمز درست بوده ولی حساب برای این صفحه مناسب نیست: در لاگ می‌آید، ولی در شمارنده‌ی مسدودی نه
            name, role, branch = record_actor(user)
            record(request, AuditLog.CATEGORY_AUTH, 'login_failed', f'ورود ناموفق: {reason}', status=AuditLog.STATUS_FAILED,
                   target_type='حساب', target_label=f'{name} ({role})', branch=branch, identifier=ctx['identifier_log'], actor=None)
            return Response({'detail': message}, status=401)

        if login_type == 'teacher' and not payload['is_employee']:
            return wrong_type('این حساب، حساب مدرس نیست.', 'حساب غیرمدرس از صفحه‌ی مدرسین')
        if login_type == 'student' and not payload['is_member']:
            return wrong_type('این حساب، حساب دانش‌پژوه نیست.', 'حساب غیردانش‌پژوه از صفحه‌ی دانش‌پژوه')
        # پنل‌های مدیریتی (پنل ادمین/مسئول آموزش) فقط برای دو سمت مشخص باز است
        STAFF_ROLES = ['مدیر آموزش', 'مسئول آموزش']
        if login_type == 'staff' and payload.get('employee_role') not in STAFF_ROLES:
            return wrong_type('این حساب به پنل مدیریتی دسترسی ندارد.', 'حسابِ بدون دسترسی از صفحه‌ی ورود مدیریتی')

        login(request, user)
        type_label = {'staff': 'پنل مدیریتی', 'teacher': 'مدرس', 'student': 'دانش‌پژوه'}.get(login_type, 'سامانه')
        throttle.succeed(request, ctx, 'login_success', f'ورود موفق ({type_label})', user)
        return Response(payload)


class LogoutView(APIView):
    def post(self, request):
        if request.user.is_authenticated:
            record(request, AuditLog.CATEGORY_AUTH, 'logout', 'خروج از سامانه')
        logout(request)
        return Response({'detail': 'خارج شدید.'})


class MeView(APIView):
    def get(self, request):
        if not request.user.is_authenticated:
            return Response({'detail': 'وارد نشده‌اید.'}, status=401)
        return Response(build_profile_payload(request.user))


# ---------------------------------------------------------------------------
# فراموشی رمز عبور و ورود با رمز یکبار مصرف - هر دو با کد ملی شروع می‌شوند
# ---------------------------------------------------------------------------

def _generate_and_send_otp(national_id, purpose, message_template):
    """
    تابع مشترک بین «فراموشی رمز عبور» و «ورود با رمز یکبار مصرف»: دانش‌پژوه
    را با کد ملی پیدا می‌کند، یک کد ۶ رقمی می‌سازد و (فعلاً به‌صورت Placeholder)
    برایش پیامک می‌کند.

    عمداً همیشه پیام موفقیت یکسان برمی‌گرداند (چه کد ملی پیدا شود چه نشود) -
    همان تدبیر امنیتی LoginView: اگر پیام‌ها فرق کنند، هرکسی می‌تواند با
    امتحان کردن کدهای ملی مختلف بفهمد کدام‌ها اصلاً در سامانه ثبت شده‌اند.
    """
    member = Member.objects.filter(national_id=national_id).select_related('user').first()
    if member is not None and member.phone:
        code = f'{random.randint(0, 999999):06d}'
        OTPCode.objects.create(
            member=member,
            code=code,
            purpose=purpose,
            expires_at=timezone.now() + timezone.timedelta(minutes=OTP_VALID_MINUTES),
        )
        send_sms(member.phone, message_template.format(code=code))
    # اگر عضو پیدا نشد یا شماره‌ی تلفنی ثبت نکرده، سکوت می‌کنیم (پیامکی درکار نیست)
    # اما پاسخ به فرانت هرحال یکسان و مبهم است.


class ForgotPasswordRequestView(APIView):
    """مرحله‌ی ۱ فراموشی رمز عبور: کد ملی می‌گیرد، کد بازیابی پیامک می‌کند."""
    permission_classes = [AllowAny]

    def post(self, request):
        national_id = (request.data.get('national_id') or '').strip()
        if not national_id:
            return Response({'detail': 'کد ملی را وارد کنید.'}, status=400)

        # محدودیت درخواست کد (جلوگیری از پیامک‌پرانی): بعد از چند بار، چند دقیقه ارسال نمی‌شود
        blocked = throttle.otp_request_gate(request, national_id)
        if blocked:
            return blocked
        _generate_and_send_otp(
            national_id,
            OTPCode.PURPOSE_RESET,
            'کد بازیابی رمز عبور سامانه سدا: {code}\nاین کد تا ۵ دقیقه معتبر است.',
        )
        return Response({
            'detail': 'اگر این کد ملی در سامانه ثبت شده باشد، کد بازیابی برای شماره‌ی ثبت‌شده پیامک می‌شود.',
        })


class ForgotPasswordConfirmView(APIView):
    """مرحله‌ی ۲ فراموشی رمز عبور: کد پیامکی + رمز عبور جدید می‌گیرد."""
    permission_classes = [AllowAny]

    def post(self, request):
        national_id = (request.data.get('national_id') or '').strip()
        code = (request.data.get('code') or '').strip()
        new_password = request.data.get('new_password') or ''

        if not national_id or not code or not new_password:
            return Response({'detail': 'کد ملی، کد پیامکی و رمز عبور جدید را وارد کنید.'}, status=400)
        if len(new_password) < 4:
            return Response({'detail': 'رمز عبور جدید باید حداقل ۴ کاراکتر باشد.'}, status=400)

        ctx, blocked = throttle.guard(national_id)
        if blocked:
            return blocked

        member = Member.objects.filter(national_id=national_id).select_related('user').first()
        otp = None
        if member is not None:
            otp = (
                OTPCode.objects
                .filter(member=member, purpose=OTPCode.PURPOSE_RESET, code=code, is_used=False)
                .order_by('-created_at')
                .first()
            )
        if otp is None or not otp.is_valid():
            return throttle.fail(request, ctx, 'reset_failed', 'تلاش ناموفق برای تغییر رمز با کد پیامکی',
                                 'کد وارد‌شده نامعتبر یا منقضی‌شده است.', 400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        member.user.set_password(new_password)
        member.user.save()
        throttle.succeed(request, ctx, 'password_reset', 'رمز عبور با کد پیامکی تغییر کرد (دانش‌پژوه)', member.user)

        return Response({'detail': 'رمز عبور با موفقیت تغییر کرد. حالا می‌توانید وارد شوید.'})


class OTPLoginRequestView(APIView):
    """مرحله‌ی ۱ ورود با رمز یکبار مصرف: کد ملی می‌گیرد، کد ورود پیامک می‌کند."""
    permission_classes = [AllowAny]

    def post(self, request):
        national_id = (request.data.get('national_id') or '').strip()
        if not national_id:
            return Response({'detail': 'کد ملی را وارد کنید.'}, status=400)

        blocked = throttle.otp_request_gate(request, national_id)
        if blocked:
            return blocked
        _generate_and_send_otp(
            national_id,
            OTPCode.PURPOSE_LOGIN,
            'کد ورود یکبارمصرف سامانه سدا: {code}\nاین کد تا ۵ دقیقه معتبر است.',
        )
        return Response({
            'detail': 'اگر این کد ملی در سامانه ثبت شده باشد، کد ورود برای شماره‌ی ثبت‌شده پیامک می‌شود.',
        })


class OTPLoginVerifyView(APIView):
    """مرحله‌ی ۲ ورود با رمز یکبار مصرف: کد پیامکی می‌گیرد و در صورت درستی، وارد می‌کند."""
    permission_classes = [AllowAny]

    def post(self, request):
        national_id = (request.data.get('national_id') or '').strip()
        code = (request.data.get('code') or '').strip()

        if not national_id or not code:
            return Response({'detail': 'کد ملی و کد پیامکی را وارد کنید.'}, status=400)

        # قفل موقت: حدس‌زدن کد پیامکی (۶ رقم) هم مثل رمز، بعد از چند تلاش ناموفق مسدود می‌شود
        ctx, blocked = throttle.guard(national_id)
        if blocked:
            return blocked

        member = Member.objects.filter(national_id=national_id).select_related('user').first()
        otp = None
        if member is not None:
            otp = (
                OTPCode.objects
                .filter(member=member, purpose=OTPCode.PURPOSE_LOGIN, code=code, is_used=False)
                .order_by('-created_at')
                .first()
            )
        if otp is None or not otp.is_valid():
            return throttle.fail(request, ctx, 'otp_login_failed', 'تلاش ناموفق برای ورود با کد پیامکی',
                                 'کد وارد‌شده نامعتبر یا منقضی‌شده است.', 400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        # چون این پروژه دو backend احراز هویت دارد (MemberAuthBackend و
        # ModelBackend پیش‌فرض جنگو)، و اینجا از authenticate() رد نشده‌ایم
        # (کد پیامکی را خودمان مستقیم بررسی کردیم، نه رمز عبور)، باید به
        # login() صریحاً بگوییم کدام backend را حساب کند - وگرنه جنگو
        # نمی‌داند و خطا می‌دهد.
        login(request, member.user, backend='django.contrib.auth.backends.ModelBackend')
        throttle.succeed(request, ctx, 'login_success', 'ورود موفق با کد پیامکی (دانش‌پژوه)', member.user)
        return Response(build_profile_payload(member.user))


# ---------------------------------------------------------------------------
# فراموشی رمز عبور برای مدرسین - دقیقاً همان ایده‌ی بالا برای دانش‌پژوه،
# با این تفاوت که به‌جای «کد ملی»، از روی «شماره موبایل» مدرس پیدا می‌شود
# (چون مدرس با نام‌کاربری اختصاصی وارد می‌شود، نه کد ملی).
#
# نکته‌ی امنیتی مهم: کوئری همیشه با role='مدرس' فیلتر می‌شود، نه فقط با
# شماره موبایل - چون phone روی Employee یکتا (unique) نیست (بر خلاف
# Member.phone)، و این مسیر عمومی است (بدون نیاز به ورود)؛ اگر فقط با
# شماره فیلتر می‌شد و یک متصدی (مدیر آموزش/مسئول آموزش) با همان شماره در
# دیتابیس بود، همین مسیر می‌توانست رمز عبور آن حساب مدیریتی را هم عوض کند.
# ---------------------------------------------------------------------------

def _find_teacher_by_phone(phone):
    return (
        Employee.objects
        .filter(phone=phone, role='مدرس', user__isnull=False)
        .select_related('user')
        .first()
    )


def _generate_and_send_employee_otp(phone, message_template):
    """
    مشابه _generate_and_send_otp بالا، اما برای مدرس: با شماره موبایل پیدا
    می‌شود (فقط اگر حساب ورود هم داشته باشد - نیروهای قدیمی بدون حساب
    نمی‌توانند رمز عبوری داشته باشند که بخواهند بازیابی کنند).

    عمداً همیشه پیام موفقیت یکسان برمی‌گرداند، حتی اگر شماره پیدا نشود -
    همان تدبیر امنیتی نسخه‌ی دانش‌پژوه.
    """
    employee = _find_teacher_by_phone(phone)
    if employee is not None:
        code = f'{random.randint(0, 999999):06d}'
        EmployeeOTPCode.objects.create(
            employee=employee,
            code=code,
            purpose=EmployeeOTPCode.PURPOSE_RESET,
            expires_at=timezone.now() + timezone.timedelta(minutes=OTP_VALID_MINUTES),
        )
        send_sms(phone, message_template.format(code=code))


class TeacherForgotPasswordRequestView(APIView):
    """مرحله‌ی ۱ فراموشی رمز مدرس: شماره موبایل می‌گیرد، کد بازیابی پیامک می‌کند."""
    permission_classes = [AllowAny]

    def post(self, request):
        phone = (request.data.get('phone') or '').strip()
        if not phone:
            return Response({'detail': 'شماره موبایل را وارد کنید.'}, status=400)

        teacher = _find_teacher_by_phone(phone)
        blocked = throttle.otp_request_gate(request, phone, user=teacher.user if teacher is not None else None)
        if blocked:
            return blocked
        _generate_and_send_employee_otp(
            phone,
            'کد بازیابی رمز عبور سامانه سدا: {code}\nاین کد تا ۵ دقیقه معتبر است.',
        )
        return Response({
            'detail': 'اگر این شماره موبایل در سامانه ثبت شده باشد، کد بازیابی برایتان پیامک می‌شود.',
        })


class TeacherForgotPasswordConfirmView(APIView):
    """مرحله‌ی ۲ فراموشی رمز مدرس: کد پیامکی + رمز عبور جدید می‌گیرد."""
    permission_classes = [AllowAny]

    def post(self, request):
        phone = (request.data.get('phone') or '').strip()
        code = (request.data.get('code') or '').strip()
        new_password = request.data.get('new_password') or ''

        if not phone or not code or not new_password:
            return Response({'detail': 'شماره موبایل، کد پیامکی و رمز عبور جدید را وارد کنید.'}, status=400)
        if len(new_password) < 4:
            return Response({'detail': 'رمز عبور جدید باید حداقل ۴ کاراکتر باشد.'}, status=400)

        employee = _find_teacher_by_phone(phone)
        # شمارنده روی «حساب مدرس» است (با هر قالبِ شماره موبایل، یک شمارنده)
        ctx, blocked = throttle.guard(phone, user=employee.user if employee is not None else None)
        if blocked:
            return blocked
        otp = None
        if employee is not None:
            otp = (
                EmployeeOTPCode.objects
                .filter(employee=employee, purpose=EmployeeOTPCode.PURPOSE_RESET, code=code, is_used=False)
                .order_by('-created_at')
                .first()
            )
        if otp is None or not otp.is_valid():
            return throttle.fail(request, ctx, 'reset_failed', 'تلاش ناموفق برای تغییر رمز مدرس با کد پیامکی',
                                 'کد وارد‌شده نامعتبر یا منقضی‌شده است.', 400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        employee.user.set_password(new_password)
        employee.user.save()
        throttle.succeed(request, ctx, 'password_reset', 'رمز عبور با کد پیامکی تغییر کرد (مدرس)', employee.user)

        return Response({'detail': 'رمز عبور با موفقیت تغییر کرد. حالا می‌توانید وارد شوید.'})


# ---------------------------------------------------------------------------
# جستجو و مدیریت اعضا - برای صفحه‌ی «اعضا» در پنل ادمین
# ---------------------------------------------------------------------------

def _member_name(member):
    return f'{member.user.first_name} {member.user.last_name}'.strip() or member.national_id


def _member_summary(action_key, label, target_label, obj, request, response):
    if action_key == 'ban':
        reason = (request.data.get('reason', '') if hasattr(request.data, 'get') else '') or 'بدون دلیل'
        return f'{label}: {target_label} — دلیل: {reason}'
    return f'{label}: {target_label}'


@audit('member', 'عضو', {
    'update': ('member_update', 'ویرایش اطلاعات عضو'),
    'ban': ('member_ban', 'اعمال محرومیت'),
    'unban': ('member_unban', 'برداشتن محرومیت'),
}, label_func=_member_name, mask_fields=('membership_code',), skip_fields=('user',), summary_func=_member_summary,
   snapshot_extra_func=lambda m: {'نام': m.user.first_name, 'نام خانوادگی': m.user.last_name})
class MemberViewSet(AuditedMixin, viewsets.ModelViewSet):
    """
    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل بقیه‌ی ViewSetهای این
    پروژه، فعلاً برای راحتی توسعه باز است. وقتی احراز هویت پنل ادمین ساخته
    شد، این را به IsAdminUser محدود کنید - چون اطلاعات شخصی اعضا (تلفن،
    کد ملی) را برمی‌گرداند.
    """
    queryset = Member.objects.select_related('user').all()
    serializer_class = MemberSearchSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_permissions(self):
        # ویرایش اطلاعات یک عضو فقط برای «مدیر آموزش» و «مسئول آموزش» است (بقیه‌ی
        # کارهای این ViewSet مثل قبل باز می‌ماند؛ نگاه کنید به TODO بالای کلاس)
        if self.action == 'partial_update':
            return [IsEducationStaff()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        # ساخت عضو از این مسیر مجاز نیست؛ افزودن دانش‌پژوه/عضو جدید فقط از
        # پنل ادمین جنگو ممکن است. POST فقط برای اکشن‌های ban/unban زیر باز است.
        return Response({'detail': 'افزودن دانش‌پژوه فقط از پنل ادمین جنگو ممکن است.'}, status=405)

    def partial_update(self, request, *args, **kwargs):
        """ویرایش اطلاعات یک عضو موجود (PATCH /api/members/<id>/) - نگاه کنید به MemberUpdateSerializer."""
        member = self.get_object()
        serializer = MemberUpdateSerializer(member, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        member = serializer.save()
        member.refresh_from_db()
        return Response(self.get_serializer(member).data)

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        national_id = (params.get('national_id') or '').strip()
        membership_code = (params.get('membership_code') or '').strip()
        first_name = (params.get('first_name') or '').strip()
        last_name = (params.get('last_name') or '').strip()

        # بدون هیچ فیلتری، عمداً لیست خالی برمی‌گردانیم (نه همه‌ی اعضا) -
        # همان چیزی که فرانت‌اند هم قبل از جستجو نمایش می‌دهد ("حداقل یک
        # فیلد را وارد کنید")؛ این از دیده‌شدن اتفاقی کل فهرست اعضا جلوگیری می‌کند.
        if self.action == 'list' and not any([national_id, membership_code, first_name, last_name]):
            return qs.none()

        if national_id:
            qs = qs.filter(national_id=national_id)
        if membership_code:
            qs = qs.filter(membership_code=membership_code)
        if first_name:
            qs = qs.filter(user__first_name__icontains=first_name)
        if last_name:
            qs = qs.filter(user__last_name__icontains=last_name)
        return qs

    @action(detail=True, methods=['post'])
    def ban(self, request, pk=None):
        member = self.get_object()
        reason = request.data.get('reason', '')
        MemberBan.objects.update_or_create(member=member, defaults={'reason': reason})
        return Response(self.get_serializer(member).data)

    @action(detail=True, methods=['post'])
    def unban(self, request, pk=None):
        member = self.get_object()
        MemberBan.objects.filter(member=member).delete()
        return Response(self.get_serializer(member).data)


class MemberVerifyView(APIView):
    """
    یک نقطه‌ی واحد برای «آیا این فرد می‌تواند ثبت‌نام کند؟» - هم پنل ادمین
    (موقع افزودن دستی دانش‌پژوه به کلاس) و هم سایت اصلی (ویزارد ثبت‌نام
    دوره در hozori-courses.html/majazi-courses.html) از همین یک مسیر
    استفاده می‌کنند تا هیچ‌وقت این دو جا با هم فرق نکنند.

    عمداً هم کد ملی هم کد عضویت با هم چک می‌شوند (نه فقط کد ملی) تا مثل
    یک تأیید هویت ساده هم عمل کند؛ اگر کد عضویت با کد ملی نخواند، همان
    پاسخ «عضو نیست» برگردانده می‌شود (نه یک خطای جدا) تا معلوم نشود کد
    ملی واقعاً در سامانه هست یا نه.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        national_id = (request.data.get('national_id') or '').strip()
        membership_code = (request.data.get('membership_code') or '').strip()
        if not national_id or not membership_code:
            return Response({'detail': 'کد ملی و کد عضویت لازم است.'}, status=400)

        # این مسیر عمومی «جفتِ کد ملی + کد عضویت» را می‌سنجد و کد عضویت همان چیزی است که دانش‌پژوه با آن
        # وارد می‌شود؛ پس بدون محدودیت، راهی برای حدس‌زدن رمز بود. جفت غلط مثل ورود ناموفق شمرده می‌شود
        # (مدیر/مسئولِ واردشده معاف است چون از پنل به‌جای دانش‌پژوه وارد می‌کند).
        is_staff_request = request.user.is_authenticated and hasattr(request.user, 'employee')
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
            not_member = {'is_member': False, 'is_valid': False, 'is_banned': False, 'ban_reason': ''}
            if ctx is None:
                return Response(not_member)
            response = throttle.fail(request, ctx, 'identity_failed', 'تلاش ناموفق برای تأیید هویت (کد ملی و کد عضویت نخواند)',
                                     'این کد ملی و کد عضویت در سامانه‌ی اعضا یافت نشد.', 200)
            if response.status_code == 200:
                response.data.update(not_member)      # شکل پاسخ قبلی برای ویزارد حفظ می‌شود
            return response
        if ctx is not None:
            throttle.register_success(ctx['key'])

        return Response({
            'is_member': True,
            'is_valid': member.is_membership_valid,
            'is_banned': hasattr(member, 'ban'),
            'ban_reason': member.ban.reason if hasattr(member, 'ban') else '',
        })
