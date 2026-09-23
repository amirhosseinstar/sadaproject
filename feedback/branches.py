"""
تطبیق دقیق نام شعبه.

فیلتر «مسئول آموزش فقط پیام‌های شعبه‌ی خودش را ببیند» به مقایسه‌ی نام شعبه
وابسته است. نام شعبه جاهای مختلف به‌صورت متن ذخیره می‌شود (فرم سایت، حساب
مسئول آموزش)، و متن ممکن است با «ي/ك» عربی، فاصله‌ی اضافه یا کاراکتر نامرئی
نوشته شده باشد؛ پس همه‌جا نام را با جدول واقعی شعب (core.Branch) تطبیق
می‌دهیم و «نام استاندارد» همان جدول را ذخیره/مقایسه می‌کنیم.
"""

import re

from core.models import Branch

_INVISIBLE_RE = re.compile('[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]')


def _normalize(text):
    """نام را برای مقایسه یکدست می‌کند (ی/ک فارسی، نیم‌فاصله، فاصله‌های تکراری)."""
    text = _INVISIBLE_RE.sub('', text or '')
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')
    return re.sub(r'\s+', ' ', text).strip().lower()


def canonical_branch_name(text):
    """
    نام استانداردِ شعبه (همان‌طور که در جدول Branch ثبت است) را برمی‌گرداند،
    یا None اگر چنین شعبه‌ای وجود نداشته باشد.
    """
    wanted = _normalize(text)
    if not wanted:
        return None
    for name in Branch.objects.values_list('name', flat=True):
        if _normalize(name) == wanted:
            return name
    return None
