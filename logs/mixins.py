"""
AuditedMixin: با اضافه‌کردن به یک ViewSet، ثبت/ویرایش/حذف (و اکشن‌های سفارشی) آن خودکار در لاگ ثبت می‌شود.

کافی است در ViewSet تعریف شود:
    audit_category = 'class'
    audit_type_label = 'کلاس'
    audit_actions = {'create': ('class_create', 'درج کلاس'), 'update': (...), 'destroy': (...), 'enroll': (...)}

  - ویرایش با «قبل و بعد» (فقط فیلدهایی که عوض شده‌اند) ثبت می‌شود؛ ویرایشِ بدون تغییر ثبت نمی‌شود.
  - فقط درخواست‌های «موفق» (۲xx) ثبت می‌شوند.
  - فیلدهای حساس (audit_mask_fields) مقدارشان در لاگ نمی‌آید، فقط «تغییر کرد».
  - خطای لاگ هرگز کار اصلی را خراب نمی‌کند.
"""

import datetime
import json

from .models import AuditLog
from .recorder import logger, record

MASKED_VALUE = 'تغییر کرد'


def _display(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'بله' if value else 'خیر'
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def snapshot(obj, skip=(), mask=(), extra=None):
    """(دیکشنری «عنوان فیلد ← مقدار»، مجموعه‌ی عنوان فیلدهای پنهان‌شونده) از یک شیء مدل."""
    data, masked = {}, set()
    for field in obj._meta.concrete_fields:
        if field.primary_key or field.name in skip:
            continue
        # فیلدهای خودکار (مثل «آخرین ویرایش» با auto_now) تغییرِ کاربر نیستند؛ در «قبل و بعد» نمی‌آیند
        if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
            continue
        label = str(field.verbose_name)
        try:
            value = getattr(obj, field.name)
            if hasattr(value, 'name') and field.get_internal_type() in ('FileField', 'ImageField'):
                value = value.name
        except Exception:
            value = None
        data[label] = _display(value)
        if field.name in mask:
            masked.add(label)
    for label, value in (extra or {}).items():
        data[label] = _display(value)
    return data, masked


def diff(before, after, masked):
    """تغییرها بین دو snapshot؛ مقدار فیلدهای حساس پنهان می‌شود."""
    changes = []
    for label, new in after.items():
        old = before.get(label, '')
        if old == new:
            continue
        if label in masked:
            changes.append({'field': label, 'old': '', 'new': MASKED_VALUE})
        else:
            changes.append({'field': label, 'old': old, 'new': new})
    return changes


def audit(category, type_label, actions, **options):
    """
    دکوراتور تنظیمات لاگ یک ViewSet (بدون دست‌زدن به بدنه‌ی کلاس):

        @audit('class', 'کلاس', {'create': ('class_create', 'درج کلاس'), ...},
               label_func=lambda o: o.name, mask_fields=('membership_code',))

    options: label_func، branch_func، summary_func، snapshot_extra_func (توابع سفارشی)،
             skip_fields، mask_fields، label_field، branch_field
    """
    def wrap(cls):
        cls.audit_category = category
        cls.audit_type_label = type_label
        cls.audit_actions = actions
        for name, value in options.items():
            # تابع‌ها staticmethod می‌شوند تا هنگام صدا زدن از روی نمونه، self به آن‌ها پاس نشود
            setattr(cls, f'audit_{name}', staticmethod(value) if callable(value) else value)
        return cls
    return wrap


class AuditedMixin:
    audit_category = AuditLog.CATEGORY_CLASS
    audit_type_label = ''
    audit_actions = {}
    audit_label_field = 'name'
    audit_branch_field = 'branch'
    audit_skip_fields = ()
    audit_mask_fields = ()
    audit_label_func = None            # تابع (شیء) ← متن مورد
    audit_branch_func = None           # تابع (شیء) ← شعبه
    audit_summary_func = None          # تابع (کلید_اکشن، عنوان، مورد، شیء، request، response) ← متن شرح
    audit_snapshot_extra_func = None   # تابع (شیء) ← دیکشنری فیلدهای اضافه (مثل نام کاربر عضو)

    # ---- نقطه‌های سفارشی‌سازی (با options دکوراتور یا بازنویسی در ViewSet) ----
    def audit_snapshot_extra(self, obj):
        return self.audit_snapshot_extra_func(obj) if self.audit_snapshot_extra_func else {}

    def audit_target_label(self, obj):
        if self.audit_label_func:
            return self.audit_label_func(obj)
        value = getattr(obj, self.audit_label_field, None)
        return str(value) if value else str(obj)

    def audit_branch(self, obj):
        if self.audit_branch_func:
            return self.audit_branch_func(obj) or ''
        return getattr(obj, self.audit_branch_field, '') or ''

    def audit_summary(self, action_key, label, target_label, obj, request, response):
        if self.audit_summary_func:
            return self.audit_summary_func(action_key, label, target_label, obj, request, response)
        return f'{label}: {target_label}' if target_label else label

    def audit_extra_changes(self, request, action_key):
        # تغییر رمز عبور (مثلاً هنگام ساخت/ویرایش مدیر و مسئول آموزش): مقدارش هرگز ثبت نمی‌شود
        data = getattr(request, 'data', None)
        if action_key in ('create', 'update') and hasattr(data, 'get') and data.get('password'):
            return [{'field': 'رمز عبور', 'old': '', 'new': 'تعیین شد' if action_key == 'create' else 'تغییر کرد'}]
        return []

    # ---- پیاده‌سازی ----
    def _audit_snapshot(self, obj):
        return snapshot(obj, self.audit_skip_fields, self.audit_mask_fields, self.audit_snapshot_extra(obj))

    def get_object(self):
        obj = super().get_object()
        if self.request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not hasattr(self, '_audit_obj'):
            self._audit_obj = obj
            self._audit_target_id = str(obj.pk)     # بعد از حذف، pk شیء None می‌شود
            self._audit_before, self._audit_masked = self._audit_snapshot(obj)
            try:
                self._audit_label_before = self.audit_target_label(obj)
                self._audit_branch_before = self.audit_branch(obj)
            except Exception:
                self._audit_label_before, self._audit_branch_before = '', ''
        return obj

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        try:
            self._audit_handle(request, response)
        except Exception:
            logger.exception('ثبت لاگِ ViewSet شکست خورد: %s', self.__class__.__name__)
        return response

    def _audit_handle(self, request, response):
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE') or not (200 <= response.status_code < 300):
            return
        name = getattr(self, 'action', None)
        key = 'update' if name in ('update', 'partial_update') else name
        entry = self.audit_actions.get(key)
        if entry is None:
            return
        code, label = entry

        obj, changes, target_id = None, [], ''
        if key == 'create':
            data = getattr(response, 'data', None)
            pk = data.get('id') if isinstance(data, dict) else None
            if pk is not None:
                model = self.get_serializer_class().Meta.model
                obj = model._default_manager.filter(pk=pk).first()
                target_id = str(pk)
        else:
            obj = getattr(self, '_audit_obj', None)
            target_id = getattr(self, '_audit_target_id', '')
            if key == 'update' and obj is not None:
                obj.refresh_from_db()
                after, _ = self._audit_snapshot(obj)
                changes = diff(self._audit_before, after, self._audit_masked)
        changes += self.audit_extra_changes(request, key)
        if key == 'update' and not changes:
            return      # ویرایش بدون تغییر واقعی: ثبت نمی‌شود

        if key == 'destroy' or obj is None:
            target_label = getattr(self, '_audit_label_before', '')
            branch = getattr(self, '_audit_branch_before', '') or (request.data.get('branch', '') if hasattr(request.data, 'get') else '')
        else:
            target_label = self.audit_target_label(obj)
            branch = self.audit_branch(obj)
        summary = self.audit_summary(key, label, target_label, obj, request, response)
        record(request, self.audit_category, code, summary, target_type=self.audit_type_label,
               target_id=target_id, target_label=target_label, branch=branch, changes=changes)
