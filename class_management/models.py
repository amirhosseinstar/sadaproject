"""
مدل‌های دپارتمان‌ها، کلاس‌ها و ثبت‌نام دانش‌پژوهان.

این‌ها جایگزین آرایه‌های مجازی (DEPARTMENTS/BRANCH_DEPTS/CLASSES) در
sada-admin.html می‌شوند که تا این فاز فقط در حافظه‌ی مرورگر بودند و با هر
بار رفرش صفحه از بین می‌رفتند.
"""

from django.db import models


class Department(models.Model):
    """یک دپارتمان آموزشی (مثل «کامپیوتر»، «دوخت و دوز»)."""
    name = models.CharField('نام دپارتمان', max_length=100, unique=True)

    class Meta:
        verbose_name = 'دپارتمان'
        verbose_name_plural = 'دپارتمان‌ها'
        ordering = ['name']

    def __str__(self):
        return self.name


class BranchDepartment(models.Model):
    """
    کدام دپارتمان‌ها در کدام شعبه فعال‌اند.

    نکته: branch فعلاً یک رشته‌ی متنی است (مثل باقی پروژه که هنوز Branch را
    به‌صورت ForeignKey همه‌جا وصل نکرده‌ایم)، نه ForeignKey به core.Branch؛
    این با الگوی فعلی Employee.branch/Member.branch هماهنگ است.
    """
    branch = models.CharField('شعبه', max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='branch_links')

    class Meta:
        verbose_name = 'دپارتمان فعال در شعبه'
        verbose_name_plural = 'دپارتمان‌های فعال در شعب'
        unique_together = ('branch', 'department')

    def __str__(self):
        return f'{self.department} در {self.branch}'


class Lesson(models.Model):
    """
    درس (سرفصل) - قبل از این‌که بتوان یک «کلاس» برایش ساخت، باید اول در
    همین‌جا تعریف شده باشد؛ کلاس فقط یک نمونه‌ی زمان‌بندی‌شده از یک درس
    است. هر شعبه درس‌های خودش را جداگانه تعریف می‌کند (ممکن است یک درس
    فقط در یک شعبه لازم باشد، نه همه‌جا).
    """
    name = models.CharField('نام درس', max_length=200)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='lessons')
    branch = models.CharField('شعبه', max_length=100, default='')
    sessions = models.PositiveIntegerField('تعداد جلسات', null=True, blank=True)
    description = models.TextField('توضیحات', blank=True)

    class Meta:
        verbose_name = 'درس'
        verbose_name_plural = 'درس‌ها'
        ordering = ['branch', 'department__name', 'name']

    def __str__(self):
        return f'{self.name} ({self.department.name})'


class Class(models.Model):
    """یک کلاس درسی (دوره) - همان چیزی که در مدیریت کلاس‌ها دیده می‌شود."""
    GENDER_CHOICES = [('مردانه', 'مردانه'), ('زنانه', 'زنانه'), ('مختلط', 'مختلط')]
    TYPE_CHOICES = [('حضوری', 'حضوری'), ('مجازی', 'مجازی')]
    DAY_CHOICES = [
        ('شنبه', 'شنبه'), ('یکشنبه', 'یکشنبه'), ('دوشنبه', 'دوشنبه'),
        ('سه‌شنبه', 'سه‌شنبه'), ('چهارشنبه', 'چهارشنبه'),
        ('پنجشنبه', 'پنجشنبه'), ('جمعه', 'جمعه'),
    ]

    name = models.CharField('نام کلاس', max_length=200)
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes',
        verbose_name='درس',
        help_text='کلاس باید بر اساس یک درسِ از قبل تعریف‌شده ساخته شود.',
    )
    class_type = models.CharField('نوع برگزاری', max_length=10, choices=TYPE_CHOICES, default='حضوری')
    is_national = models.BooleanField(
        'سراسری (بدون وابستگی به شعبه)', default=False,
        help_text='فقط برای کلاس‌های مجازی معنی دارد - یعنی دانش‌پژوهان همه‌ی شعب می‌بینندش.',
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='classes')
    branch = models.CharField('شعبه', max_length=100, blank=True)
    teacher = models.ForeignKey(
        'core.Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='classes',
    )
    term = models.ForeignKey(
        'academic_calendar.AcademicTerm', on_delete=models.SET_NULL, null=True, blank=True, related_name='held_classes',
    )
    capacity = models.PositiveIntegerField('ظرفیت')
    has_online_exam = models.BooleanField(
        'آزمون آنلاین دارد', default=False,
        help_text='اگر فعال باشد، در «درج نمرات» فقط ۵۰ نمره (نمره‌ی عملی) قابل ثبت دستی است؛ ۵۰ نمره‌ی دیگر برای آزمون آنلاین کنار گذاشته می‌شود.',
    )
    # تاریخ شروع فعلاً متنی است (مثل «۱۴۰۴/۰۳/۱۵») - همان قالبی که فرانت‌اند
    # قبلاً هم استفاده می‌کرد؛ چون فقط برای نمایش است، نه محاسبه.
    start_date = models.CharField('تاریخ شروع', max_length=20, blank=True)
    day = models.CharField('روز هفته', max_length=50, blank=True)
    start_time = models.CharField('ساعت شروع', max_length=10, blank=True)
    entry_time = models.CharField('ساعت پایان/ورود', max_length=10, blank=True)

    @property
    def duration_hours_raw(self):
        """
        مدت کل دوره (به ساعت، دقیق و بدون رند) - همیشه خودکار محاسبه
        می‌شود، هیچ‌جا دستی وارد نمی‌شود: هر دوره یک ماه (۴ هفته) فرض
        می‌شود؛ تعداد روزهای هفته (از روی همان چندین‌روزی که هنگام درج
        کلاس انتخاب شده) در تعداد ساعت هر جلسه (فاصله‌ی ساعت شروع تا
        ساعت پایان) و در ۴ هفته ضرب می‌شود.
        """
        if not self.day or not self.start_time or not self.entry_time:
            return None
        days_count = len([d for d in self.day.split('،') if d.strip()])
        if days_count == 0:
            return None
        try:
            sh, sm = (int(x) for x in self.start_time.split(':'))
            eh, em = (int(x) for x in self.entry_time.split(':'))
        except (ValueError, AttributeError):
            return None
        session_hours = (eh * 60 + em - (sh * 60 + sm)) / 60
        if session_hours <= 0:
            return None
        return days_count * 4 * session_hours

    gender = models.CharField('جنسیت', max_length=10, choices=GENDER_CHOICES, default='مختلط')
    prerequisite = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name='dependent_classes',
        verbose_name='درسِ پیش‌نیاز',
        help_text=(
            'پیش‌نیاز به «درس» وصل است نه به یک کلاس خاص - چون کلاس‌ها هر ترم '
            'عوض می‌شوند ولی درس ثابت می‌ماند. یعنی حتی اگر الان کلاسی برای آن '
            'درس برگزار نشود، بازهم می‌شود آن را به‌عنوان پیش‌نیاز انتخاب کرد.',
        ),
    )
    is_published = models.BooleanField('منتشرشده در سایت', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'کلاس'
        verbose_name_plural = 'کلاس‌ها'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.branch})'

    @property
    def enrolled_count(self):
        return self.enrollments.count()

    @property
    def is_full(self):
        return self.enrolled_count >= self.capacity


class Enrollment(models.Model):
    """
    ثبت‌نام یک دانش‌پژوه در یک کلاس.

    نکته‌ی مهم: class_obj عمداً SET_NULL است (نه CASCADE) - اگر بعداً خودِ
    کلاس حذف شود، سابقه‌ی ثبت‌نام از بین نمی‌رود (چون برای پیش‌نیازها و
    گزارش‌های آینده لازم است بدانیم فرد این درس را گذرانده، حتی اگر آن
    کلاس خاص دیگر وجود نداشته باشد). به همین دلیل lesson هم مستقیم و
    جداگانه (نه فقط از طریق class_obj) روی خودِ ثبت‌نام ذخیره می‌شود.
    """
    class_obj = models.ForeignKey(
        Class, on_delete=models.SET_NULL, null=True, blank=True, related_name='enrollments',
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name='enrollments',
        help_text='کپی مستقل از درسِ همان کلاس در لحظه‌ی ثبت‌نام - حتی اگر بعداً کلاس حذف شود باقی می‌ماند.',
    )
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField('تاریخ ثبت‌نام', auto_now_add=True)
    score = models.PositiveSmallIntegerField(
        'نمره', null=True, blank=True,
        help_text='اگر کلاس «آزمون آنلاین» فعال داشته باشد، حداکثر ۵۰ (نمره‌ی عملی)؛ وگرنه حداکثر ۱۰۰.',
    )
    absent = models.BooleanField(
        'غایب در کلاس', default=False,
        help_text='اگر فرد اصلاً در کلاس حضور نداشته، این True می‌شود و نمره خودکار صفر می‌شود - حتی اگر کلاس آزمون آنلاین هم داشته باشد، دیگر اجازه‌ی شرکت در آن را ندارد (چون در خودِ کلاس شرکت نکرده است). این حالت باعث می‌شود در «سوابق آموزشی» به‌جای «مردود - عدم کسب نمره کافی»، دقیقاً «مردود - عدم حضور در کلاس» نشان داده شود.',
    )

    class Meta:
        verbose_name = 'ثبت‌نام'
        verbose_name_plural = 'ثبت‌نام‌ها'
        unique_together = ('class_obj', 'member')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f'{self.member} در {self.class_obj or self.lesson}'


class SiteSettings(models.Model):
    """
    تنظیمات سراسری سایت - فقط یک رکورد باید وجود داشته باشد (singleton).

    دسترسی همگان به ثبت‌نام سه حالت دارد:
    - «خودکار»: خودش بر اساس تقویم آموزشی تشخیص می‌دهد - اگر امروز داخل
      بازه‌ی «ثبت‌نام» یکی از دوره‌های تقویم باشد، سایت باز است، وگرنه بسته.
    - «باز - دستی»: مدیر آموزش با دکمه‌ی دستی، صرف‌نظر از تقویم، سایت را
      همیشه باز نگه می‌دارد.
    - «بسته - دستی»: همان‌طور، ولی همیشه بسته.
    """
    MODE_CHOICES = [
        ('auto', 'خودکار (بر اساس تقویم آموزشی)'),
        ('open', 'باز - همیشه (دستی)'),
        ('closed', 'بسته - همیشه (دستی)'),
    ]
    registration_mode = models.CharField(
        'وضعیت دسترسی همگان به ثبت‌نام', max_length=10, choices=MODE_CHOICES, default='auto',
    )

    class Meta:
        verbose_name = 'تنظیمات سایت'
        verbose_name_plural = 'تنظیمات سایت'

    @property
    def public_registration_enabled(self):
        """
        مقدار نهایی (True/False) که بقیه‌ی کدها (مثل enroll) باید ازش
        استفاده کنند - این‌جا دقیقاً همان سه حالت بالا محاسبه می‌شود.
        """
        if self.registration_mode == 'open':
            return True
        if self.registration_mode == 'closed':
            return False
        return self._is_today_in_any_registration_window()

    def _is_today_in_any_registration_window(self):
        from academic_calendar.models import AcademicTerm
        from sada_project.utils import today_jalali

        jy, jm, jd = today_jalali()
        today_value = jy * 10000 + jm * 100 + jd

        for term in AcademicTerm.objects.filter(year=jy, is_active=True):
            reg = term.registration
            start_value = term.year * 10000 + reg['start']['m'] * 100 + reg['start']['d']
            end_value = term.year * 10000 + reg['end']['m'] * 100 + reg['end']['d']
            if start_value <= today_value <= end_value:
                return True
        return False

    class Meta:
        verbose_name = 'تنظیمات سایت'
        verbose_name_plural = 'تنظیمات سایت'

    def save(self, *args, **kwargs):
        self.pk = 1  # همیشه فقط همین یک رکورد وجود دارد
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # عمداً قابل حذف نیست

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return 'تنظیمات سراسری سایت'
