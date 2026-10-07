"""
بخش‌های قابل «باز/بسته‌شدن» برای «مسئول آموزش».

«مدیر آموزش» همیشه به همه‌چیز دسترسی دارد و می‌تواند دسترسی هر مسئول آموزش را به هر بخش (از فهرست
SECTIONS) ببندد یا دوباره باز کند. پیش‌فرض همه‌ی بخش‌ها «باز» است؛ بخش‌های بسته‌شده‌ی هر مسئول در
Employee.denied_sections ذخیره می‌شود.

اجرای قفل در یک جا و بر اساس «آدرس API» انجام می‌شود (core/middleware.py)، نه داخل تک‌تک ViewSetها؛ پس
حتی اگر فرانت‌اند منوی یک بخش را مخفی نکرده باشد، سرور درخواست مسئول را رد می‌کند.
قاعده‌ی «مسئول فقط به شعبه‌ی خودش دسترسی دارد» جداست و داخل خودِ ViewSetها اعمال می‌شود.

اگر ViewSet یا بخش تازه‌ای اضافه شد، فقط کافی است همین‌جا یک خط به SECTIONS و/یا RULES اضافه شود.
"""

import re

from core.permissions import ROLE_MANAGER, ROLE_OFFICER, staff_role

# (کلید، عنوانی که در پنل مدیر نشان داده می‌شود)
SECTIONS = [
    ('classes', 'کلاس‌ها، سمینارها، دروس و ثبت‌نام/نمرات'),
    ('questions', 'بانک سؤال'),
    ('teachers', 'مدرسین و درخواست‌های همکاری'),
    ('members', 'اعضا (دانش‌پژوهان)'),
    ('feedback', 'انتقادات و پیشنهادات'),
    ('survey', 'نظرسنجی کلاس‌ها'),
    ('finance', 'امور مالی'),
    ('logs', 'لاگ سامانه'),
]
SECTION_KEYS = [key for key, _ in SECTIONS]
SECTION_LABELS = dict(SECTIONS)

_WRITE = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

# (الگوی آدرس، روش‌های درخواست [None = همه]، کلید بخش) - اولین تطابق برنده است.
# خواندنِ اطلاعات «عمومی» (کلاس‌ها، درس‌ها، سمینارها، تقویم، شعب) برای سایت عمومی لازم است و قفل نمی‌شود؛
# فقط «نوشتن» آن‌ها (و مسیرهای شخصی/حساس) به بخش وابسته است.
RULES = [
    (re.compile(r'^/api/finance/'), None, 'finance'),
    (re.compile(r'^/api/logs/'), None, 'logs'),
    (re.compile(r'^/api/core/employees/'), None, 'teachers'),
    (re.compile(r'^/api/core/teacher-applicants/'), None, 'teachers'),
    (re.compile(r'^/api/classmgmt/teacher-permissions/'), None, 'teachers'),
    # فقط مدیریت اعضا (لیست و /<id>/...)؛ نه /api/members/verify/ که عمومی است
    (re.compile(r'^/api/members/(\d+/.*)?$'), None, 'members'),
    (re.compile(r'^/api/classmgmt/questions/'), None, 'questions'),
    (re.compile(r'^/api/classmgmt/enrollments/'), None, 'classes'),
    (re.compile(r'^/api/classmgmt/(classes|seminars)/\d+/students/'), None, 'classes'),
    (re.compile(r'^/api/classmgmt/(classes|seminars|lessons)/'), _WRITE, 'classes'),
    (re.compile(r'^/api/feedback/class-survey/'), None, 'survey'),
    (re.compile(r'^/api/feedback/'), None, 'feedback'),
]


def section_for_request(path, method):
    """کلید بخشی که این درخواست به آن تعلق دارد، یا None اگر به هیچ بخش قفل‌شدنی‌ای وابسته نیست."""
    for pattern, methods, section in RULES:
        if pattern.match(path) and (methods is None or method in methods):
            return section
    return None


def denied_sections(user):
    """بخش‌هایی که برای این «مسئول آموزش» بسته است (برای هر کاربر دیگر لیست خالی)."""
    if staff_role(user) != ROLE_OFFICER:
        return []
    return [k for k in (getattr(user.employee, 'denied_sections', None) or []) if k in SECTION_LABELS]


def allowed_sections(user):
    """بخش‌هایی که این کاربرِ مدیریتی می‌تواند ببیند (مدیر: همه؛ مسئول: همه به‌جز بسته‌شده‌ها؛ غیرِ آن: هیچ)."""
    role = staff_role(user)
    if role == ROLE_MANAGER:
        return list(SECTION_KEYS)
    if role == ROLE_OFFICER:
        closed = set(denied_sections(user))
        return [k for k in SECTION_KEYS if k not in closed]
    return []
