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

from .models import Member, MemberBan, OTPCode
from .serializers import MemberSearchSerializer, build_profile_payload
from .sms import send_sms

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

        user = authenticate(request, username=username, password=password)
        if user is None:
            # پیام یکسان برای هر دو حالت («کاربر وجود ندارد» یا «رمز اشتباه است»):
            # این یک تدبیر امنیتی استاندارد است، چون اگر پیام‌ها فرق کنند، هرکسی
            # می‌تواند با امتحان کردن کدهای مختلف بفهمد کدام کد ملی/عضویت اصلاً
            # در سامانه ثبت شده - حتی بدون این‌که رمزش را بداند.
            return Response(
                {'detail': 'ورود ناموفق بود؛ نام کاربری یا گذرواژه را بررسی کنید.'},
                status=401,
            )

        payload = build_profile_payload(user)

        if login_type == 'teacher' and not payload['is_employee']:
            return Response(
                {'detail': 'این حساب، حساب مدرس نیست.'},
                status=401,
            )
        if login_type == 'student' and not payload['is_member']:
            return Response(
                {'detail': 'این حساب، حساب دانش‌پژوه نیست.'},
                status=401,
            )
        # پنل‌های مدیریتی (پنل ادمین/مسئول آموزش) فقط برای دو سمت مشخص باز است
        STAFF_ROLES = ['مدیر آموزش', 'مسئول آموزش']
        if login_type == 'staff' and payload.get('employee_role') not in STAFF_ROLES:
            return Response(
                {'detail': 'این حساب به پنل مدیریتی دسترسی ندارد.'},
                status=401,
            )

        login(request, user)
        return Response(payload)


class LogoutView(APIView):
    def post(self, request):
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
            return Response({'detail': 'کد وارد‌شده نامعتبر یا منقضی‌شده است.'}, status=400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        member.user.set_password(new_password)
        member.user.save()

        return Response({'detail': 'رمز عبور با موفقیت تغییر کرد. حالا می‌توانید وارد شوید.'})


class OTPLoginRequestView(APIView):
    """مرحله‌ی ۱ ورود با رمز یکبار مصرف: کد ملی می‌گیرد، کد ورود پیامک می‌کند."""
    permission_classes = [AllowAny]

    def post(self, request):
        national_id = (request.data.get('national_id') or '').strip()
        if not national_id:
            return Response({'detail': 'کد ملی را وارد کنید.'}, status=400)

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
            return Response({'detail': 'کد وارد‌شده نامعتبر یا منقضی‌شده است.'}, status=400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        # چون این پروژه دو backend احراز هویت دارد (MemberAuthBackend و
        # ModelBackend پیش‌فرض جنگو)، و اینجا از authenticate() رد نشده‌ایم
        # (کد پیامکی را خودمان مستقیم بررسی کردیم، نه رمز عبور)، باید به
        # login() صریحاً بگوییم کدام backend را حساب کند - وگرنه جنگو
        # نمی‌داند و خطا می‌دهد.
        login(request, member.user, backend='django.contrib.auth.backends.ModelBackend')
        return Response(build_profile_payload(member.user))


# ---------------------------------------------------------------------------
# جستجو و مدیریت اعضا - برای صفحه‌ی «اعضا» در پنل ادمین
# ---------------------------------------------------------------------------

class MemberViewSet(viewsets.ModelViewSet):
    """
    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل بقیه‌ی ViewSetهای این
    پروژه، فعلاً برای راحتی توسعه باز است. وقتی احراز هویت پنل ادمین ساخته
    شد، این را به IsAdminUser محدود کنید - چون اطلاعات شخصی اعضا (تلفن،
    کد ملی) را برمی‌گرداند.
    """
    queryset = Member.objects.select_related('user').all()
    serializer_class = MemberSearchSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'post', 'head', 'options']

    def create(self, request, *args, **kwargs):
        # ساخت عضو از این مسیر مجاز نیست (اعضا فقط از طریق ثبت‌نام واقعی
        # ساخته می‌شوند)؛ POST فقط برای اکشن‌های ban/unban زیر باز است.
        return Response({'detail': 'ساخت عضو از این مسیر مجاز نیست.'}, status=405)

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

        member = (
            Member.objects
            .filter(national_id=national_id, membership_code=membership_code)
            .select_related('ban')
            .first()
        )
        if member is None:
            return Response({'is_member': False, 'is_valid': False, 'is_banned': False, 'ban_reason': ''})

        return Response({
            'is_member': True,
            'is_valid': member.is_membership_valid,
            'is_banned': hasattr(member, 'ban'),
            'ban_reason': member.ban.reason if hasattr(member, 'ban') else '',
        })
