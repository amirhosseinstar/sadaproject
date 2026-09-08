from django.core.exceptions import ValidationError
from django.db import models

from sada_project.utils import to_persian_digits


def validate_date_range(value):
    """
    مطمئن می‌شود که یک بازه‌ی تاریخ، شکل درستی دارد:
    {"start": {"m": 1, "d": 7}, "end": {"m": 1, "d": 13}}
    (همان ساختاری که فرانت‌اند - سدا.html - انتظارش را دارد)
    """
    if not isinstance(value, dict) or 'start' not in value or 'end' not in value:
        raise ValidationError('این فیلد باید شامل start و end باشد، مثلاً {"start":{"m":1,"d":7},"end":{"m":1,"d":13}}')
    for key in ('start', 'end'):
        point = value[key]
        if not isinstance(point, dict) or 'm' not in point or 'd' not in point:
            raise ValidationError(f'"{key}" باید شامل m (ماه) و d (روز) باشد')
        if not (1 <= int(point['m']) <= 12):
            raise ValidationError('ماه باید بین ۱ تا ۱۲ باشد')
        if not (1 <= int(point['d']) <= 31):
            raise ValidationError('روز باید بین ۱ تا ۳۱ باشد')


class AcademicTerm(models.Model):
    """
    یک «دوره»/«ترم» در تقویم آموزشی (همان ردیف‌های جدول تقویم آموزشی).

    چهار بازه‌ی تاریخ دارد: ثبت‌نام، برگزاری کلاس، جابه‌جایی، آزمون نهایی.
    هر بازه به شکل JSON ذخیره می‌شود چون تاریخ‌ها شمسی هستند و فقط
    ماه/روز دارند (نه تاریخ کامل میلادی) - دقیقاً همان چیزی که جدول
    تقویم آموزشی در سایت اصلی و پنل ادمین نشان می‌دهند.
    """
    year = models.PositiveIntegerField('سال (شمسی)')
    order = models.PositiveSmallIntegerField('شماره‌ی دوره در سال')

    registration = models.JSONField('بازه‌ی ثبت‌نام', validators=[validate_date_range])
    classes = models.JSONField('بازه‌ی برگزاری کلاس', validators=[validate_date_range])
    move = models.JSONField('بازه‌ی جابه‌جایی', validators=[validate_date_range])
    exam = models.JSONField('بازه‌ی آزمون نهایی', validators=[validate_date_range])

    is_active = models.BooleanField('فعال', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'دوره‌ی تقویم آموزشی'
        verbose_name_plural = 'تقویم آموزشی'
        unique_together = ('year', 'order')
        ordering = ['year', 'order']

    def __str__(self):
        return f'دوره {self.code} - سال {self.year}'

    @property
    def code(self):
        """برچسب نمایشی دوره، مثل «۰۱» - همان چیزی که در سایت به‌جای period دیده می‌شود."""
        return to_persian_digits(self.order)


class CalendarDocument(models.Model):
    """
    فایل PDF رسمی تقویم آموزشی برای یک سال خاص.

    این جدا از AcademicTerm است: AcademicTerm داده‌ی ساختاریافته‌ی هر دوره
    (برای جدول و هایلایت خودکار) را نگه می‌دارد، اما این مدل فقط یک فایل
    ضمیمه‌ی PDF است که مدیر آموزش می‌تواند آپلود کند تا دانش‌پژوهان بتوانند
    نسخه‌ی رسمی/کامل تقویم را از سایت اصلی دانلود کنند. هر سال حداکثر یک
    فایل دارد؛ آپلود دوباره برای همان سال، فایل قبلی را جایگزین می‌کند.
    """
    year = models.PositiveIntegerField('سال (شمسی)', unique=True)
    pdf = models.FileField('فایل PDF', upload_to='calendar_pdfs/')
    uploaded_at = models.DateTimeField('زمان آپلود', auto_now=True)

    class Meta:
        verbose_name = 'فایل PDF تقویم آموزشی'
        verbose_name_plural = 'فایل‌های PDF تقویم آموزشی'
        ordering = ['-year']

    def __str__(self):
        return f'تقویم PDF سال {self.year}'
