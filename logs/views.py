# ===== مسیر این فایل در پروژه: logs/views.py (کنار manage.py) =====
"""
API خواندن لاگ (فقط مدیر آموزش و مسئول آموزش؛ مسئول فقط رویدادهای شعبه‌ی خودش).

  GET /api/logs/          فهرست صفحه‌بندی‌شده + شمارنده‌های هشدار (۲۴ ساعت گذشته)
  GET /api/logs/export/   همان فیلترها، به‌صورت فایل CSV (حداکثر ۵۰٬۰۰۰ ردیف)

فیلترها: category، status، q (جستجو)، date_from و date_to (تاریخ شمسی)، page، page_size
لاگ فقط خواندنی است؛ هیچ endpoint ویرایش یا حذفی ندارد.
"""

import csv
import io
import re
from datetime import datetime, time, timedelta

from django.db.models import F, Q, Value
from django.db.models.functions import Replace
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import ROLE_OFFICER, IsEducationStaff, staff_role
from feedback.branches import canonical_branch_name
from sada_project.utils import jalali_to_gregorian, parse_jalali_date, to_english_digits

from .models import AuditLog, LoginThrottle
from .recorder import record

MAX_PAGE_SIZE = 200
EXPORT_LIMIT = 50000
# دسته‌ی «مدرسین و کارکنان» به دو دسته‌ی «مدرسین» و «کارکنان» شکسته شد. لاگ فقط اضافه می‌شود و رکوردهای
# قدیمی را نمی‌شود عوض کرد؛ پس رکوردهای قدیمی که با دسته‌ی 'staff' ثبت شده ولی مربوط به مدرس‌اند، هنگام
# «خواندن» (فیلتر، نمایش، خروجی) در دسته‌ی «مدرسین» حساب می‌شوند. رکوردهای جدید مستقیم با دسته‌ی درست ثبت می‌شوند.
LEGACY_TEACHER_ACTIONS = (
    'teacher_update', 'teacher_delete', 'teacher_permission_update',
    'applicant_create', 'applicant_update', 'applicant_delete', 'applicant_approve',
)
CATEGORY_LABELS = dict(AuditLog.CATEGORY_CHOICES)


def effective_category(log):
    """دسته‌ی واقعیِ یک رکورد (با نگاشت رکوردهای قدیمی «مدرسین و کارکنان»)."""
    if log.category == AuditLog.CATEGORY_STAFF and log.action in LEGACY_TEACHER_ACTIONS:
        return AuditLog.CATEGORY_TEACHER
    return log.category


# رویدادهایی که «بدون ورود» بودنشان طبیعی است (فرم عمومی مدرس، ثبت‌نام با کد ملی/کد عضویت)؛ در هشدار
# «تغییر بدون ورود» شمرده نمی‌شوند. هر تغییرِ مدیریتی دیگری که ناشناس انجام دهد یعنی مسیرش برای عموم باز است.
PUBLIC_ANONYMOUS_ACTIONS = ('applicant_create', 'class_enroll', 'enroll_rejected')


def _jalali_to_datetime(text, end_of_day):
    """تاریخ شمسی متنی را به زمان (ابتدا/انتهای آن روز، به وقت تهران) تبدیل می‌کند؛ نامعتبر = None."""
    parsed = parse_jalali_date(text, allow_future=True) if text else None     # فیلتر بازه، تاریخ آینده هم می‌پذیرد
    if parsed is None:
        return None
    gy, gm, gd = jalali_to_gregorian(*parsed)
    day = datetime.combine(datetime(gy, gm, gd).date(), time(23, 59, 59) if end_of_day else time(0, 0, 0))
    return timezone.make_aware(day)


def _scoped_queryset(request):
    """لاگ‌هایی که این کاربر حق دیدنشان را دارد (مسئول آموزش: فقط شعبه‌ی خودش)."""
    qs = AuditLog.objects.all()
    if staff_role(request.user) == ROLE_OFFICER:
        branch = canonical_branch_name(request.user.employee.branch) or (request.user.employee.branch or '').strip()
        return qs.filter(branch=branch) if branch else qs.none()
    return qs


def _digits_to_english_expr(field_name):
    """
    عبارت SQL که ارقام فارسی (۰-۹) و عربی (٠-٩) ستون را به انگلیسی تبدیل می‌کند.
    متن لاگ‌ها (مثل «۹۶۰٬۰۰۰ تومان») ارقام فارسی دارد ولی کاربر ممکن است با ارقام انگلیسی جستجو کند.
    """
    expr = F(field_name)
    for i in range(10):
        expr = Replace(expr, Value(chr(0x06F0 + i)), Value(str(i)))
        expr = Replace(expr, Value(chr(0x0660 + i)), Value(str(i)))
    return expr


_THOUSANDS_SEPARATORS = ('٬', ',', '،')


def _apply_search(qs, q):
    """
    جستجوی متنی لاگ. هم ارقامِ فارسی/انگلیسی و هم جداکننده‌ی هزارگان («٬» «,» «،») را یکسان می‌بیند، پس
    «960000»، «۹۶۰۰۰۰»، «960,000» و «۹۶۰٬۰۰۰» همه رویدادِ «۹۶۰٬۰۰۰ تومان» را پیدا می‌کنند.
    همچنین «ي/ك» عربیِ صفحه‌کلید با «ی/ک» فارسی یکی حساب می‌شود.
    """
    q = to_english_digits(q).replace('ي', 'ی').replace('ك', 'ک')
    numeric_only = re.fullmatch(r'[0-9\s,٬،]+', q) is not None
    plain_number = re.sub(r'[\s,٬،]', '', q) if numeric_only else ''

    qs = qs.annotate(summary_en=_digits_to_english_expr('summary'), target_en=_digits_to_english_expr('target_label'))
    condition = (
        Q(summary_en__icontains=q) | Q(target_en__icontains=q) | Q(actor_name__icontains=q)
        | Q(identifier__icontains=q) | Q(ip__icontains=q) | Q(action__icontains=q)
    )
    if plain_number:
        # عدد: در متنِ بدون جداکننده‌ی هزارگان هم جستجو کن (۹۶۰٬۰۰۰ ← 960000)
        summary_plain = Replace(
            Replace(Replace(F('summary_en'), Value('٬'), Value('')), Value(','), Value('')), Value('،'), Value(''),
        )
        qs = qs.annotate(summary_plain=summary_plain)
        condition |= Q(summary_plain__icontains=plain_number)
    return qs.filter(condition)


def _filtered(request):
    qs = _scoped_queryset(request)
    params = request.query_params
    category = params.get('category')
    if category == AuditLog.CATEGORY_TEACHER:
        qs = qs.filter(Q(category=AuditLog.CATEGORY_TEACHER) | Q(category=AuditLog.CATEGORY_STAFF, action__in=LEGACY_TEACHER_ACTIONS))
    elif category == AuditLog.CATEGORY_STAFF:
        qs = qs.filter(category=AuditLog.CATEGORY_STAFF).exclude(action__in=LEGACY_TEACHER_ACTIONS)
    elif category:
        qs = qs.filter(category=category)
    status = params.get('status')
    if status:
        qs = qs.filter(status=status)
    action = params.get('action')
    if action:
        qs = qs.filter(action=action)
    # لاگ ثبت‌نامِ یک کلاس مشخص («لیست کلاس‌ها» در صفحه‌ی لاگ): تطبیق با شناسه‌ی همان کلاس
    class_id = params.get('class_id')
    if class_id:
        qs = qs.filter(target_type='کلاس', target_id=str(class_id))
    q = (params.get('q') or '').strip()
    if q:
        qs = _apply_search(qs, q)
    # تاریخ نامعتبر قبلاً بی‌صدا نادیده گرفته می‌شد و «همه‌ی لاگ‌ها» برمی‌گشت؛ کاربر فکر می‌کرد فیلتر اعمال شده
    raw_from = (params.get('date_from') or '').strip()
    raw_to = (params.get('date_to') or '').strip()
    start = _jalali_to_datetime(raw_from, end_of_day=False)
    end = _jalali_to_datetime(raw_to, end_of_day=True)
    if raw_from and start is None:
        raise ValidationError({'detail': 'تاریخ شروع نامعتبر است؛ یک تاریخ شمسی مثل ۱۴۰۵/۰۷/۱۰ وارد کنید.'})
    if raw_to and end is None:
        raise ValidationError({'detail': 'تاریخ پایان نامعتبر است؛ یک تاریخ شمسی مثل ۱۴۰۵/۰۷/۱۰ وارد کنید.'})
    if start and end and start > end:
        raise ValidationError({'detail': 'تاریخ شروع نباید بعد از تاریخ پایان باشد.'})
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    return qs


def _row(log):
    category = effective_category(log)
    return {
        'id': log.id,
        'created_at': log.created_at,
        'category': category,
        'category_display': CATEGORY_LABELS.get(category, category),
        'action': log.action,
        'summary': log.summary,
        'status': log.status,
        'status_display': log.get_status_display(),
        'actor_name': log.actor_name,
        'actor_role': log.actor_role,
        'branch': log.branch,
        'target_type': log.target_type,
        'target_label': log.target_label,
        'changes': log.changes,
        'identifier': log.identifier,
        'ip': log.ip,
        'user_agent': log.user_agent,
    }


class LogListView(APIView):
    permission_classes = [IsEducationStaff]

    def get(self, request):
        qs = _filtered(request)
        try:
            page = max(1, int(request.query_params.get('page', 1)))
            size = min(MAX_PAGE_SIZE, max(1, int(request.query_params.get('page_size', 50))))
        except ValueError:
            return Response({'detail': 'پارامتر صفحه‌بندی نامعتبر است.'}, status=http_status.HTTP_400_BAD_REQUEST)
        total = qs.count()
        rows = [_row(l) for l in qs[(page - 1) * size: page * size]]

        # شمارنده‌های هشدار ۲۴ ساعت گذشته (در محدوده‌ی دسترسی همین کاربر)
        since = timezone.now() - timedelta(hours=24)
        recent = _scoped_queryset(request).filter(created_at__gte=since)
        summary = {
            'failed_logins': recent.filter(category=AuditLog.CATEGORY_AUTH, status=AuditLog.STATUS_FAILED).count(),
            'lockouts': recent.filter(category=AuditLog.CATEGORY_AUTH, status=AuditLog.STATUS_BLOCKED).count(),
            # تغییرِ مدیریتیِ موفق که «بدون ورود به سامانه» انجام شده (هشدار امنیتی: آن مسیر برای عموم باز است)
            'anonymous_changes': recent.filter(actor__isnull=True, actor_name='', status=AuditLog.STATUS_SUCCESS)
                                       .exclude(category=AuditLog.CATEGORY_AUTH).exclude(action__in=PUBLIC_ANONYMOUS_ACTIONS).count(),
        }
        if staff_role(request.user) != ROLE_OFFICER:
            # تلاش با نام‌های ناشناس در لاگ تک‌تک ثبت نمی‌شود (فقط شمرده می‌شود)؛ فقط مدیر آن را می‌بیند
            # فقط شمارنده‌های «ورود/تأیید هویت» (نه محدودیت درخواست کد پیامکی که کلیدش با otpreq: شروع می‌شود)
            summary['unknown_attempts'] = LoginThrottle.objects.filter(key__startswith='unknown:', last_attempt_at__gte=since).count()
            summary['active_lockouts'] = LoginThrottle.objects.filter(locked_until__gt=timezone.now()).exclude(key__startswith='otpreq:').count()
        return Response({'count': total, 'page': page, 'page_size': size, 'results': rows, 'summary': summary})


def _csv_safe(value):
    """
    جلوگیری از «تزریق فرمول» در اکسل: سلولی که با = + - @ (یا تب/ENTER) شروع شود، در اکسل فرمول اجرا می‌کند.
    متن لاگ شاملِ ورودیِ کاربرانِ عمومی است (مثلاً نامِ متقاضیِ فرم عمومی)، پس چنین سلولی با «'» شروع
    می‌شود تا فقط به‌عنوان متن نشان داده شود.
    """
    text = '' if value is None else str(value)
    return "'" + text if text and text[0] in ('=', '+', '-', '@', '\t', '\r') else text


class LogExportView(APIView):
    permission_classes = [IsEducationStaff]

    def get(self, request):
        qs = _filtered(request)[:EXPORT_LIMIT]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['زمان', 'دسته', 'رویداد', 'وضعیت', 'انجام‌دهنده', 'سمت', 'شعبه', 'مورد', 'شناسه‌ی واردشده', 'IP', 'تغییرات'])
        for log in qs:
            changes = ' | '.join(
                f"{c.get('field', '')}: {c.get('old', '')} ← {c.get('new', '')}" if c.get('old') else f"{c.get('field', '')}: {c.get('new', '')}"
                for c in (log.changes or [])
            )
            writer.writerow([_csv_safe(cell) for cell in [
                timezone.localtime(log.created_at).strftime('%Y-%m-%d %H:%M:%S'), CATEGORY_LABELS.get(effective_category(log), log.category), log.summary,
                log.get_status_display(), log.actor_name, log.actor_role, log.branch, log.target_label,
                log.identifier, log.ip or '', changes,
            ]])
        # BOM تا اکسل متن فارسی را درست باز کند
        response = HttpResponse('\ufeff' + buffer.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="audit-log.csv"'
        # خودِ گرفتنِ خروجی هم در لاگ ثبت می‌شود (چه کسی، چه فیلترهایی، چند ردیف)
        filters = {k: v for k, v in request.query_params.items() if v}
        record(request, AuditLog.CATEGORY_SETTINGS, 'log_export', 'دریافت خروجی CSV از لاگ', target_type='لاگ',
               changes=[{'field': 'فیلترها', 'old': '', 'new': ' | '.join(f'{k}={v}' for k, v in filters.items()) or 'بدون فیلتر'}])
        return response
