from django.conf import settings
from django.db import models


class Branch(models.Model):
    """
    شعبه‌ی خانه کارگر. این لیست، داده‌ی واقعی سازمان است (نه نمونه)،
    برای همین در همه‌جای سایت که لیست شعب لازم است، باید از همین جدول
    خوانده شود - نه از یک آرایه‌ی ثابت در کد HTML.
    """
    name = models.CharField('نام شعبه', max_length=150, unique=True)
    province = models.CharField(
        'استان', max_length=100, blank=True,
        help_text='برای محدودکردن ثبت‌نام دانش‌پژوهان به کلاس‌های همان استان لازم است.',
    )
    address = models.CharField('آدرس', max_length=300, blank=True)
    phone = models.CharField('شماره تلفن', max_length=30, blank=True)

    class Meta:
        verbose_name = 'شعبه'
        verbose_name_plural = 'شعب'
        ordering = ['name']

    def __str__(self):
        return self.name


class Employee(models.Model):
    """
    نیروی انسانی (مدرس / مسئول آموزش / مدیر آموزش).

    این مدل از قبل در پروژه وجود داشت (قبل از این‌که کدهایتان گم شود) و
    داده‌ی واقعی هم داخلش هست، برای همین دقیقاً با همان ساختار قبلی
    نوشته شده تا داده‌ی موجود در db.sqlite3 حفظ شود و چیزی خراب نشود.

    TODO (فاز بعدی - دپارتمان‌ها و کلاس‌ها): این مدل هنوز کامل نیست:
    - role باید به‌جای متن آزاد، از چند گزینه‌ی مشخص انتخاب شود (choices)
    - branch باید به مدل واقعی Branch وصل شود (ForeignKey) نه فقط متن
    این تغییرات در فاز «دپارتمان‌ها و کلاس‌ها» انجام می‌شود تا مرحله به مرحله پیش برویم.
    (به‌روزرسانی: depts دیگر تک‌مقداره نیست - حالا یک لیست است، چون یک
    مدرس می‌تواند هم‌زمان در چند دپارتمان تدریس کند.)

    فیلد user (ورود به سایت):
    مشابه Member، هر مدرس هم می‌تواند به یک حساب کاربری جنگو وصل شود تا
    بتواند در «teacher-login.html» وارد شود. برخلاف دانش‌پژوه (که با کد ملی
    وارد می‌شود)، اینجا طبق تصمیم پروژه از «نام کاربری اختصاصی» که خود ادمین
    تعیین می‌کند استفاده می‌شود (یعنی همان User.username پیش‌فرض جنگو، بدون
    نیاز به بک‌اند احراز هویت سفارشی). این فیلد nullable است چون نیروهای
    قدیمی‌ای که از قبل در دیتابیس هستند، لزوماً حساب ورود ندارند؛ ادمین بعداً
    می‌تواند برایشان حساب بسازد.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='employee',
        verbose_name='حساب کاربری (ورود به سایت)',
        null=True,
        blank=True,
    )
    name = models.CharField('نام و نام خانوادگی', max_length=150)
    role = models.CharField('سمت', max_length=50)
    depts = models.JSONField('دپارتمان‌ها', default=list, blank=True)
    branch = models.CharField('شعبه', max_length=100)
    phone = models.CharField('شماره تماس', max_length=20)

    # این فیلدها فقط برای مدرسین پر می‌شوند (از روی همان اطلاعاتی که موقع
    # ثبت‌نامِ متقاضی گرفته شده بود) - برای متصدیان (مدیر/مسئول آموزش) خالی می‌مانند
    national_id = models.CharField('کد ملی', max_length=10, blank=True)
    father_name = models.CharField('نام پدر', max_length=100, blank=True)
    birth_date = models.CharField('تاریخ تولد', max_length=20, blank=True, help_text='به شمسی، مثلاً: ۱۳۷۰/۰۵/۱۲')
    education_level = models.CharField('میزان تحصیلات', max_length=20, blank=True)
    address = models.CharField('آدرس', max_length=300, blank=True)
    photo = models.FileField('عکس', upload_to='employee_photos/', null=True, blank=True)
    resume = models.FileField('رزومه', upload_to='employee_resumes/', null=True, blank=True)

    class Meta:
        verbose_name = 'نیروی انسانی'
        verbose_name_plural = 'نیروی انسانی'

    def __str__(self):
        return f'{self.name} ({self.role})'


class TeacherApplicant(models.Model):
    """
    درخواست همکاری یک مدرس متقاضی - از دو راه ساخته می‌شود:
      ۱) عمومی: فرم «teacher-registration.html» (هرکسی بدون ورود می‌تواند پر کند)
      ۲) دستی: فرم «افزودن مدرس متقاضی» در پنل ادمین/مسئول آموزش

    بعد از بررسی توسط ادمین/مسئول آموزش، یا رد می‌شود (حذف رکورد) یا تأیید
    می‌شود. موقع تأیید، یک رکورد Employee واقعی (با role='مدرس') از روی
    اطلاعات همین درخواست ساخته می‌شود. این تنها راه ساخته شدن یک «مدرس» در
    سامانه است؛ از پنل ادمین دیگر نمی‌شود مستقیماً مدرس جدید اضافه کرد
    (نگاه کنید به core/views.py::TeacherApplicantViewSet.approve).

    نکته‌ی مهم درباره‌ی نام‌کاربری/رمز عبور: بر خلاف نسخه‌ی قبلی، این‌ها
    دیگر بخشی از فرم ثبت‌نام نیستند - متقاضی چیزی درباره‌ی حساب ورودش وارد
    نمی‌کند. نام‌کاربری و رمز عبور فقط همان لحظه‌ی تأیید (approve)، مستقیماً
    از ادمین/مسئول آموزش پرسیده می‌شود (چه در پنل سفارشی HTML چه در پنل
    جنگو) و به‌عنوان پارامتر به approve_teacher_applicant داده می‌شود -
    برای همین این مدل دیگر فیلدی برای نام‌کاربری/رمز ندارد.
    """
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'در انتظار بررسی'),
        (STATUS_APPROVED, 'تأییدشده'),
    ]
    REQTYPE_CHOICES = [('حضوری', 'حضوری'), ('مجازی', 'مجازی')]
    SOURCE_CHOICES = [
        ('سایت', 'ثبت از طریق سایت'),
        ('دستی', 'ثبت دستی توسط ادمین'),
    ]

    EDUCATION_LEVEL_CHOICES = [
        ('سیکل', 'سیکل'),
        ('دیپلم', 'دیپلم'),
        ('کاردانی', 'کاردانی'),
        ('کارشناسی', 'کارشناسی'),
        ('کارشناسی ارشد', 'کارشناسی ارشد'),
        ('دکتری', 'دکتری'),
    ]

    first_name = models.CharField('نام', max_length=100)
    last_name = models.CharField('نام خانوادگی', max_length=100)
    national_id = models.CharField('کد ملی', max_length=10, blank=True)
    education_level = models.CharField(
        'میزان تحصیلات', max_length=20, choices=EDUCATION_LEVEL_CHOICES, blank=True,
    )
    father_name = models.CharField('نام پدر', max_length=100, blank=True)
    # مثل بقیه‌ی تاریخ‌های این پروژه، عمداً متنی و شمسی است (نه DateField میلادی)
    birth_date = models.CharField('تاریخ تولد', max_length=20, blank=True, help_text='به شمسی، مثلاً: ۱۳۷۰/۰۵/۱۲')
    depts = models.JSONField('دپارتمان‌ها', default=list, blank=True)
    reqtype = models.JSONField('نوع همکاری درخواستی', default=list, blank=True)
    regtype = models.CharField(
        'منبع ثبت', max_length=10, choices=SOURCE_CHOICES, default='دستی',
        help_text='این فیلد نشان می‌دهد درخواست از طریق سایت اصلی ثبت شده یا مدیر/مسئول آموزش دستی اضافه‌اش کرده - ربطی به نوع همکاری (حضوری/مجازی) ندارد.',
    )
    branch = models.CharField('شعبه', max_length=100, blank=True)
    phone = models.CharField('شماره تماس', max_length=15)
    address = models.CharField('آدرس', max_length=300, blank=True)
    photo = models.FileField('عکس', upload_to='teacher_applicants/photos/', blank=True, null=True)
    resume = models.FileField('رزومه', upload_to='teacher_applicants/resumes/', blank=True, null=True)
    message = models.TextField('توضیحات متقاضی', blank=True)
    status = models.CharField('وضعیت', max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField('تاریخ ثبت', auto_now_add=True)

    class Meta:
        verbose_name = 'مدرس متقاضی'
        verbose_name_plural = 'مدرسین متقاضی'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.first_name} {self.last_name}'
