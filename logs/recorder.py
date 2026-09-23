"""
ثبت رویداد در لاگ: تابع record().

ویژگی‌های مهم:
  - هرگز خطا بالا نمی‌دهد؛ اگر ثبت لاگ به هر دلیل شکست بخورد، کارِ اصلی (مثلاً ذخیره‌ی پرداخت) خراب
    نمی‌شود (فقط خطا در لاگ فایلیِ «audit» ثبت می‌شود).
  - رمز عبور و کد عضویت را هرگز نمی‌گیرد (فراخوان‌ها مقدارشان را نمی‌دهند).
  - شعبه را با نام استانداردِ جدول شعب ذخیره می‌کند تا فیلتر «مسئول آموزش فقط شعبه‌ی خودش» دقیق باشد.
"""

import ipaddress
import logging
from datetime import timedelta

from django.utils import timezone

from feedback.branches import canonical_branch_name

from . import policy
from .models import AuditLog

logger = logging.getLogger('audit')


def client_ip(request):
    """آدرس IP درخواست. (پشت پراکسی فقط با LOGS_TRUST_PROXY_HEADER=True از X-Forwarded-For خوانده می‌شود.)"""
    if request is None:
        return None
    raw = ''
    if policy.trust_proxy_header():
        raw = (request.META.get('HTTP_X_FORWARDED_FOR', '') or '').split(',')[0].strip()
    raw = raw or request.META.get('REMOTE_ADDR', '') or ''
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def actor_info(user):
    """(نام، سمت، شعبه) کاربر برای ثبت در لاگ؛ برای کاربر ناشناس رشته‌های خالی."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return '', '', ''
    employee = getattr(user, 'employee', None)
    if employee is not None:
        return employee.name, employee.role, employee.branch or ''
    member = getattr(user, 'member', None)
    if member is not None:
        name = f'{user.first_name} {user.last_name}'.strip() or user.get_username()
        return name, 'دانش‌پژوه', member.branch or ''
    return (user.get_full_name() or user.get_username()), ('مدیر سیستم' if user.is_superuser else 'کاربر'), ''


def _clip(value, size):
    return str(value if value is not None else '')[:size]


def _clean_changes(changes):
    cleaned = []
    for change in (changes or [])[:40]:
        cleaned.append({
            'field': _clip(change.get('field'), 80),
            'old': _clip(change.get('old'), 300),
            'new': _clip(change.get('new'), 300),
        })
    return cleaned


def record(request, category, action, summary, *, status=AuditLog.STATUS_SUCCESS, target=None,
           target_type='', target_id='', target_label='', branch=None, changes=None,
           identifier='', actor=None):
    """
    یک رویداد را در لاگ ثبت می‌کند و رکورد را برمی‌گرداند (یا در صورت شکست None).

    actor: اگر ندهید، کاربرِ واردشده‌ی همین درخواست است. برای رویدادهای «ورود» که هنوز
           request.user به‌روز نشده، کاربر را صریح بدهید.
    branch: شعبه‌ی مربوط به رویداد؛ اگر ندهید، شعبه‌ی خودِ انجام‌دهنده.
    """
    try:
        user = actor if actor is not None else (getattr(request, 'user', None) if request is not None else None)
        name, role, actor_branch = actor_info(user)
        if target is not None:
            target_id = target_id or str(getattr(target, 'pk', ''))
        branch_value = (branch or actor_branch or '').strip()
        canonical = canonical_branch_name(branch_value) or branch_value
        return AuditLog.objects.create(
            category=category,
            action=_clip(action, 40),
            summary=_clip(summary, 300),
            status=status,
            actor=user if (user is not None and getattr(user, 'is_authenticated', False)) else None,
            actor_name=_clip(name, 150),
            actor_role=_clip(role, 40),
            branch=_clip(canonical, 100),
            target_type=_clip(target_type, 40),
            target_id=_clip(target_id, 40),
            target_label=_clip(target_label, 200),
            changes=_clean_changes(changes),
            identifier=_clip(identifier, 150),
            ip=client_ip(request),
            user_agent=_clip(request.META.get('HTTP_USER_AGENT', '') if request is not None else '', 300),
        )
    except Exception:
        logger.exception('ثبت رویداد در لاگ شکست خورد: %s / %s', category, action)
        return None


def record_dedup(request, category, action, summary, *, window_minutes=10, **kwargs):
    """
    مثل record()، ولی اگر «همان رویداد» (همان دسته/کد/شرح/شناسه/مورد) در window_minutes دقیقه‌ی
    گذشته قبلاً ثبت شده باشد، دوباره ثبت نمی‌کند. برای رویدادهای «رد شدن» که کاربر ممکن است
    پشت‌سرهم تکرارشان کند (مثلاً چند بار ثبت‌نام در کلاسِ پر)؛ چون لاگ همیشگی است و پاک نمی‌شود.
    """
    try:
        since = timezone.now() - timedelta(minutes=window_minutes)
        exists = AuditLog.objects.filter(
            category=category, action=_clip(action, 40), summary=_clip(summary, 300),
            identifier=_clip(kwargs.get('identifier', ''), 150), target_id=_clip(kwargs.get('target_id', ''), 40),
            created_at__gte=since,
        ).exists()
        if exists:
            return None
    except Exception:
        logger.exception('بررسی تکراری‌بودن رویداد لاگ شکست خورد')
    return record(request, category, action, summary, **kwargs)
