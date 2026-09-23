# ===== مسیر این فایل در پروژه: logs/throttle.py (کنار manage.py) =====
"""
قفل موقت ورود: بعد از چند تلاش ناموفق پشت‌سرهم، «حساب» چند دقیقه مسدود می‌شود.

چند تصمیم طراحی:
  - شمارنده روی «حساب» است، نه روی رشته‌ی واردشده: یک دانش‌پژوه را می‌شود با کد ملی، کد عضویت یا
    موبایل صدا زد؛ اگر شمارنده روی رشته بود، مهاجم با عوض‌کردن آن‌ها چند برابر تلاش می‌گرفت.
  - برای نام‌های ناشناس هم شمارنده هست (تا حدس‌زدن نام کاربری بی‌هزینه نباشد)، ولی در لاگِ
    همیشگی «تک‌تک» ثبت نمی‌شوند (فقط شمرده می‌شوند) تا حمله‌ی انبوه، لاگ را بی‌نهایت بزرگ نکند.
  - تلاشِ ورود در زمان مسدودی، شمرده و ثبت نمی‌شود (مسدودی تمدید نمی‌شود و لاگ پر نمی‌شود).
  - ورود موفق، شمارنده را پاک می‌کند.
  - مسدودی فقط روی «حساب» است، نه IP: پشت پراکسی همه‌ی کاربران یک IP دارند و قفل IP همه را بیرون می‌کرد.
"""

import logging
import math
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response

from core.models import Employee
from members.models import Member
from sada_project.utils import to_english_digits, to_persian_digits

from . import policy
from .models import AuditLog, LoginThrottle
from .recorder import actor_info, record

logger = logging.getLogger('audit')

User = get_user_model()


def normalize_identifier(text):
    """شناسه‌ی واردشده را یکدست می‌کند (ارقام انگلیسی، بدون فاصله‌ی اضافه، حروف کوچک)."""
    return to_english_digits(text or '').strip().lower()[:150]


SECRET_IDENTIFIER_LABEL = 'کد عضویت (پنهان)'


def account_key(identifier):
    """
    (کلید حساب، آیا حساب واقعی است، کاربر) برای یک شناسه‌ی واردشده.
    دانش‌پژوه: کد ملی/کد عضویت/موبایل؛ کارمند: نام کاربری یا موبایل مدرس.
    """
    if not identifier:
        return 'unknown:', False, None
    member = Member.objects.filter(
        Q(national_id=identifier) | Q(membership_code=identifier) | Q(phone=identifier)
    ).select_related('user').first()
    if member is not None:
        return f'member:{member.pk}', True, member.user
    user = User.objects.filter(username__iexact=identifier).first()
    if user is not None:
        return f'user:{user.pk}', True, user
    employee = Employee.objects.filter(phone=identifier).select_related('user').first()
    if employee is not None and employee.user_id:
        return f'user:{employee.user_id}', True, employee.user
    return f'unknown:{identifier}'[:170], False, None


def blocked_seconds(key):
    """چند ثانیه‌ی دیگر این حساب مسدود است (۰ = مسدود نیست)."""
    row = LoginThrottle.objects.filter(key=key).first()
    if row is not None and row.locked_until is not None:
        remaining = (row.locked_until - timezone.now()).total_seconds()
        if remaining > 0:
            return int(math.ceil(remaining))
    return 0


def _purge_stale(now):
    """شمارنده‌های قدیمی (بیش از ۲ روز بی‌فعالیت و بدون مسدودی) پاک می‌شوند تا جدول کوچک بماند."""
    LoginThrottle.objects.filter(last_attempt_at__lt=now - timedelta(days=2)).filter(
        Q(locked_until__isnull=True) | Q(locked_until__lt=now)
    ).delete()


def register_failure(key, known, max_failures=None, window_minutes=None, lockout_minutes=None):
    """
    یک تلاش ناموفق را می‌شمارد. برمی‌گرداند:
      {'locked': bool, 'attempts_left': int|None, 'block_seconds': int}
    سقف/بازه/مدت مسدودی اختیاری‌اند (پیش‌فرض: سیاست ورود)؛ برای محدودیت «درخواست کد پیامکی» مقدار دیگری می‌گیرند.
    """
    max_failures = max_failures or policy.max_failures()
    window_minutes = window_minutes or policy.window_minutes()
    lockout_minutes = lockout_minutes or policy.lockout_minutes()
    now = timezone.now()
    with transaction.atomic():
        row, created = LoginThrottle.objects.select_for_update().get_or_create(
            key=key, defaults={'last_attempt_at': now, 'known': known},
        )
        if row.window_started_at is None or now - row.window_started_at > timedelta(minutes=window_minutes):
            row.fail_count = 0
            row.window_started_at = now
        row.fail_count += 1
        row.last_attempt_at = now
        row.known = known
        locked = row.fail_count >= max_failures
        if locked:
            row.locked_until = now + timedelta(minutes=lockout_minutes)
            row.fail_count = 0
            row.window_started_at = None
        row.save()
        attempts_left = None if locked else max(0, max_failures - row.fail_count)
    if created and random.random() < 0.1:
        _purge_stale(now)
    return {
        'locked': locked,
        'attempts_left': attempts_left,
        'block_seconds': lockout_minutes * 60 if locked else 0,
    }


def register_success(key):
    """ورود موفق: شمارنده‌ی تلاش‌های ناموفق آن حساب پاک می‌شود."""
    LoginThrottle.objects.filter(key=key).delete()


def blocked_message(seconds):
    minutes = max(1, int(math.ceil(seconds / 60)))
    return f'ورود به‌خاطر تلاش‌های ناموفق زیاد موقتاً مسدود است؛ {to_persian_digits(minutes, pad=0)} دقیقه دیگر دوباره تلاش کنید.'


def blocked_response(seconds):
    """پاسخ ۴۲۹ برای حسابِ مسدود (پیام فارسی در detail؛ صفحه‌های ورود آن را نشان می‌دهند)."""
    return Response({'detail': blocked_message(seconds), 'blocked': True, 'retry_after_seconds': seconds}, status=429)


def key_for_user(user):
    """کلید حساب برای کاربری که از قبل پیدا شده (هم‌کلید با account_key: دانش‌پژوه ← member، بقیه ← user)."""
    member = getattr(user, 'member', None)
    return f'member:{member.pk}' if member is not None else f'user:{user.pk}'


def _log_identifier(user, identifier):
    """شناسه‌ی واردشده برای لاگ؛ «کد عضویت» (که می‌تواند رمز باشد) هرگز ذخیره نمی‌شود."""
    member = getattr(user, 'member', None) if user is not None else None
    if member is not None and member.membership_code and member.membership_code == identifier:
        return SECRET_IDENTIFIER_LABEL
    return identifier


def otp_blocked_message(seconds):
    minutes = max(1, int(math.ceil(seconds / 60)))
    return f'تعداد درخواست کد پیامکی زیاد بوده است؛ {to_persian_digits(minutes, pad=0)} دقیقه دیگر دوباره تلاش کنید.'


def otp_request_gate(request, raw_identifier, user=None):
    """
    محدودیت «درخواست کد پیامکی» (ورود با کد یکبارمصرف و فراموشی رمز): برای هر حساب حداکثر
    OTP_MAX_REQUESTS درخواست در بازه؛ بعد از آن چند دقیقه پیامکی فرستاده نمی‌شود (هم جلوی
    «پیامک‌پرانی» به شماره‌ی یک نفر و هزینه‌ی پیامک را می‌گیرد).

    رفتار برای شناسه‌ی ناشناس دقیقاً مثل حساب واقعی است (شمارش و ۴۲۹ یکسان) تا از روی پاسخ
    نشود فهمید حساب وجود دارد یا نه. فقط درخواست‌های حساب‌های واقعی در لاگ ثبت می‌شوند.
    برمی‌گرداند: پاسخ ۴۲۹ (اگر محدود است) یا None (اگر اجازه‌ی ارسال هست).
    """
    identifier = normalize_identifier(raw_identifier)
    try:
        if user is not None:
            base_key, known = key_for_user(user), True
        else:
            base_key, known, user = account_key(identifier)
        key = f'otpreq:{base_key}'[:170]
        seconds = blocked_seconds(key)
        if seconds:
            return Response({'detail': otp_blocked_message(seconds), 'blocked': True, 'retry_after_seconds': seconds}, status=429)
        # (سقف+۱)امین درخواست همان است که رد می‌شود؛ درخواست‌های قبلی مجازند
        result = register_failure(key, known, max_failures=policy.otp_max_requests() + 1,
                                  window_minutes=policy.otp_window_minutes(), lockout_minutes=policy.otp_block_minutes())
    except Exception:
        # مثل guard(): اگر خودِ محدودیت خطا بدهد، به‌جای بلوکه‌کردن همه‌ی درخواست‌های کد پیامکی،
        # فقط همین محدودیت غیرفعال می‌شود و درخواست کد عادی ارسال می‌شود
        logger.exception('بررسی محدودیت درخواست کد پیامکی شکست خورد؛ بدون محدودیت ادامه می‌یابد')
        return None
    name, role, branch = actor_info(user) if known else ('', '', '')
    if result['locked']:
        if known:
            record(request, AuditLog.CATEGORY_AUTH, 'otp_request_blocked',
                   f'درخواست‌های کد پیامکی «{name}» زیاد بود؛ تا {to_persian_digits(policy.otp_block_minutes(), pad=0)} دقیقه ارسال کد محدود شد',
                   status=AuditLog.STATUS_BLOCKED, target_type='حساب', target_label=f'{name} ({role})', branch=branch,
                   identifier=_log_identifier(user, identifier), actor=None)
        return Response({'detail': otp_blocked_message(result['block_seconds']), 'blocked': True,
                         'retry_after_seconds': result['block_seconds']}, status=429)
    if known:
        record(request, AuditLog.CATEGORY_AUTH, 'otp_request', 'درخواست کد پیامکی (ورود یا بازیابی رمز)',
               target_type='حساب', target_label=f'{name} ({role})', branch=branch,
               identifier=_log_identifier(user, identifier), actor=None)
    return None


def guard(raw_identifier, user=None):
    """
    قبل از بررسی رمز/کد صدا زده می‌شود. برمی‌گرداند (ctx, پاسخ_مسدودی_یا_None) که ctx برای
    فراخوانی‌های بعدی (fail/success) است. اگر حساب از قبل پیدا شده (مثلاً مدرس با شماره موبایل)،
    user را بدهید تا شمارنده روی همان حساب باشد.
    """
    identifier = normalize_identifier(raw_identifier)
    try:
        if user is not None:
            key, known = key_for_user(user), True
        else:
            key, known, user = account_key(identifier)
        # «کد عضویت» می‌تواند رمز ورود دانش‌پژوه باشد؛ اگر کسی آن را به‌جای نام کاربری وارد کرد، در لاگ نمی‌آید
        is_secret = bool(user is not None and getattr(user, 'member', None) is not None
                         and user.member.membership_code and user.member.membership_code == identifier)
        ctx = {'identifier': identifier, 'key': key, 'known': known, 'user': user,
               'identifier_log': SECRET_IDENTIFIER_LABEL if is_secret else identifier}
        seconds = blocked_seconds(key)
        return ctx, (blocked_response(seconds) if seconds else None)
    except Exception:
        # قفل موقت یک ویژگیِ کمکی است، نه شرطِ ورود: اگر خودش (مثلاً بعد از یک به‌روزرسانی که
        # هنوز «migrate» نشده) خطا بدهد، نباید کل سامانه را از ورود بیندازد - ورود بدون قفل ادامه می‌یابد
        logger.exception('بررسی قفل موقت ورود شکست خورد؛ ورود بدون قفل ادامه می‌یابد')
        return {'identifier': identifier, 'key': None, 'known': False, 'user': user, 'identifier_log': identifier}, None


def fail(request, ctx, action, summary, base_message, status_code=401):
    """
    یک تلاش ناموفق را می‌شمارد و (برای حساب‌های واقعی) در لاگ ثبت می‌کند؛ پاسخ خطا را می‌سازد.
    اگر با این تلاش سقف پر شد، حساب مسدود و رویداد «مسدودی» هم ثبت می‌شود.

    اگر خودِ شمارش/ثبت با خطا مواجه شود (مثلاً جدول‌های لاگ هنوز migrate نشده)، تلاش ناموفق شمرده
    نمی‌شود ولی همان پیامِ خطای معمولیِ «رمز اشتباه» برمی‌گردد - ورود خراب نمی‌شود، فقط قفل موقت غیرفعال است.
    """
    if ctx.get('key') is None:
        return Response({'detail': base_message}, status=status_code)
    try:
        result = register_failure(ctx['key'], ctx['known'])
    except Exception:
        logger.exception('ثبت تلاش ناموفق ورود شکست خورد؛ ورود بدون قفل ادامه می‌یابد')
        return Response({'detail': base_message}, status=status_code)
    name, role, branch = actor_info(ctx['user']) if ctx['known'] else ('', '', '')
    if ctx['known']:
        record(request, AuditLog.CATEGORY_AUTH, action, summary, status=AuditLog.STATUS_FAILED,
               target_type='حساب', target_label=f'{name} ({role})', branch=branch, identifier=ctx['identifier_log'], actor=None)
        if result['locked']:
            record(request, AuditLog.CATEGORY_AUTH, 'lockout',
                   f'حساب «{name}» به‌مدت {to_persian_digits(policy.lockout_minutes(), pad=0)} دقیقه مسدود شد (تلاش‌های ناموفق پشت‌سرهم)',
                   status=AuditLog.STATUS_BLOCKED, target_type='حساب', target_label=f'{name} ({role})',
                   branch=branch, identifier=ctx['identifier_log'], actor=None)

    message = base_message
    if result['locked']:
        message = blocked_message(result['block_seconds'])
    elif result['attempts_left'] is not None and (policy.max_failures() - result['attempts_left']) >= policy.warn_after():
        message = (f'{base_message} (فقط {to_persian_digits(result["attempts_left"], pad=0)} تلاش دیگر باقی مانده است؛ '
                   f'بعد از آن حساب {to_persian_digits(policy.lockout_minutes(), pad=0)} دقیقه مسدود می‌شود.)')
    body = {'detail': message}
    if result['locked']:
        body.update({'blocked': True, 'retry_after_seconds': result['block_seconds']})
        return Response(body, status=429)
    if result['attempts_left'] is not None:
        body['attempts_left'] = result['attempts_left']
    return Response(body, status=status_code)


def succeed(request, ctx, action, summary, user, category=AuditLog.CATEGORY_AUTH):
    """ورود/عملیات موفق: شمارنده پاک و رویداد موفق ثبت می‌شود (خطای احتمالی، ورود موفق را خراب نمی‌کند)."""
    try:
        if ctx.get('key') is not None:
            register_success(ctx['key'])
    except Exception:
        logger.exception('پاک‌کردن شمارنده‌ی ورود موفق شکست خورد')
    record(request, category, action, summary, actor=user, identifier=ctx['identifier_log'])
