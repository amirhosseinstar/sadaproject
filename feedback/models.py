from django.db import models


class Feedback(models.Model):
    """
    یک «انتقاد» یا «پیشنهاد» که از فرم عمومی سایت اصلی (sada.html) ثبت شده.

    جریان کار:
      ۱) دانش‌پژوهِ واردشده از سایت اصلی یک مورد ثبت می‌کند
         -> وضعیت «در انتظار پاسخ» (pending)
      ۲) مدیر آموزش / مسئول آموزش آن را در پنل (بخش «بررسی و پاسخ») می‌بیند
         و پاسخ را ثبت می‌کند -> وضعیت «پاسخ داده شده» (answered)

    نکته: شعبه مثل TeacherApplicant.branch متن است، ولی موقع ثبت با جدول
    واقعی شعب تطبیق داده و به‌صورت «نام استاندارد» ذخیره می‌شود؛ مسئول آموزش
    فقط مواردی را می‌بیند که شعبه‌شان برابر شعبه‌ی خودش باشد. شعبه اختیاری است
    و مواردِ بدون شعبه فقط برای مدیر آموزش دیده می‌شوند.
    """
    KIND_COMPLAINT = 'complaint'
    KIND_SUGGESTION = 'suggestion'
    KIND_CHOICES = [
        (KIND_COMPLAINT, 'انتقاد'),
        (KIND_SUGGESTION, 'پیشنهاد'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_ANSWERED = 'answered'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'بررسی نشده'),
        (STATUS_ANSWERED, 'پاسخ داده شد'),
    ]

    # فرستنده: ثبت پیام فقط برای دانش‌پژوه واردشده ممکن است. SET_NULL است تا اگر
    # بعداً حساب دانش‌پژوه حذف شد، خودِ پیام و پاسخش از بین نرود.
    member = models.ForeignKey(
        'members.Member', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='feedbacks', verbose_name='فرستنده',
    )
    kind = models.CharField('نوع', max_length=12, choices=KIND_CHOICES)
    phone = models.CharField('شماره تماس', max_length=15, blank=True)
    branch = models.CharField('شعبه', max_length=100, blank=True)
    message = models.TextField('متن پیام')
    status = models.CharField('وضعیت', max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)

    # اطلاعات پاسخ - تا وقتی پاسخی ثبت نشده، خالی می‌مانند
    replier_name = models.CharField('نام پاسخ‌دهنده', max_length=100, blank=True)
    reply_text = models.TextField('متن پاسخ', blank=True)
    replied_at = models.DateTimeField('تاریخ پاسخ', null=True, blank=True)

    created_at = models.DateTimeField('تاریخ ثبت', auto_now_add=True)

    class Meta:
        verbose_name = 'انتقاد/پیشنهاد'
        verbose_name_plural = 'انتقادات و پیشنهادات'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_kind_display()} - {self.branch or "بدون شعبه"} ({self.get_status_display()})'


# ---------------------------------------------------------------------------
# نظرسنجی کلی کلاس
# ---------------------------------------------------------------------------
# فقط «یک» نظرسنجی برای همه‌ی دانش‌پژوهان وجود دارد (نه به‌ازای هر کلاس/ترم)
# و قرار است شرکت در آن برای دریافت مدرک اجباری باشد. مدیر/مسئول آموزش
# عنوان آن را ویرایش می‌کند و سؤال (تستی یا تشریحی) اضافه/ویرایش/حذف می‌کند.

# گزینه‌های استاندارد سؤال‌های تستی (هم پیش‌فرض سؤال جدید، هم در سؤال‌های نمونه)
DEFAULT_CHOICE_OPTIONS = ['خیلی خوب', 'خوب', 'متوسط', 'بد', 'خیلی بد']

# سؤال‌های اولیه‌ی نظرسنجی؛ فقط یک‌بار، موقع ساخته شدن نظرسنجی، اضافه می‌شوند
# و بعد از آن کاملاً قابل ویرایش/حذف‌اند.
DEFAULT_SURVEY_QUESTIONS = [
    ('کیفیت تدریس مدرس را چگونه ارزیابی می‌کنید؟', 'choice', DEFAULT_CHOICE_OPTIONS),
    ('محتوای آموزشی ارائه‌شده تا چه حد کاربردی بود؟', 'choice', DEFAULT_CHOICE_OPTIONS),
    ('امکانات و فضای برگزاری کلاس را چگونه می‌بینید؟', 'choice', DEFAULT_CHOICE_OPTIONS),
    ('نظر یا پیشنهاد خود را برای بهبود کلاس‌ها بنویسید.', 'text', []),
]


class ClassSurvey(models.Model):
    """
    نظرسنجی کلی کلاس - singleton: همیشه فقط یک رکورد (pk=1) وجود دارد
    (مثل class_management.SiteSettings) و قابل حذف نیست.
    """
    title = models.CharField('عنوان نظرسنجی', max_length=200, default='نظرسنجی پایان دوره')
    description = models.TextField(
        'توضیحات', blank=True,
        default='لطفاً پیش از دریافت مدرک، به این پرسش‌ها پاسخ دهید. نظر شما به بهبود کلاس‌ها کمک می‌کند.',
    )
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'نظرسنجی کلی کلاس'
        verbose_name_plural = 'نظرسنجی کلی کلاس'

    def save(self, *args, **kwargs):
        self.pk = 1  # همیشه فقط همین یک رکورد
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # عمداً قابل حذف نیست

    @classmethod
    def load(cls):
        """
        نظرسنجی را برمی‌گرداند و اگر هنوز ساخته نشده، همراه با چند سؤال
        نمونه (هم تستی هم تشریحی) می‌سازد تا مدیر از یک نقطه‌ی شروع ویرایش کند.
        """
        obj, created = cls.objects.get_or_create(pk=1)
        if created:
            for order, (text, kind, options) in enumerate(DEFAULT_SURVEY_QUESTIONS, start=1):
                ClassSurveyQuestion.objects.create(
                    survey=obj, text=text, kind=kind, options=list(options), order=order,
                )
        return obj

    def __str__(self):
        return self.title


class ClassSurveyQuestion(models.Model):
    """
    یک سؤال نظرسنجی کلی:
      - تستی (choice): چند گزینه‌ی قابل‌ویرایش؛ دانش‌پژوه یکی را انتخاب می‌کند
      - تشریحی (text): دانش‌پژوه پاسخ را آزاد می‌نویسد (options همیشه خالی)
    """
    KIND_CHOICE = 'choice'
    KIND_TEXT = 'text'
    KIND_CHOICES = [(KIND_CHOICE, 'تستی'), (KIND_TEXT, 'تشریحی')]

    survey = models.ForeignKey(ClassSurvey, on_delete=models.CASCADE, related_name='questions')
    text = models.CharField('متن سؤال', max_length=500)
    kind = models.CharField('نوع', max_length=6, choices=KIND_CHOICES, default=KIND_CHOICE)
    options = models.JSONField('گزینه‌ها', default=list, blank=True)
    order = models.PositiveIntegerField('ترتیب', default=0)

    class Meta:
        verbose_name = 'سؤال نظرسنجی'
        verbose_name_plural = 'سؤال‌های نظرسنجی'
        ordering = ['order', 'id']

    def __str__(self):
        return self.text


class ClassSurveyResponse(models.Model):
    """
    شرکت یک دانش‌پژوه در نظرسنجی کلی، برای «یک ثبت‌نام (کلاس)» مشخص.

    قاعده: هر ثبت‌نام فقط یک‌بار می‌تواند نظرسنجی را پر کند (OneToOne)، و
    دانش‌پژوه برای دریافت مدرک همان کلاس باید حتماً آن را پر کرده باشد
    (نگاه کنید به certificate.html و ClassSurveySubmitView).

    نکته‌ی مهم: پاسخ‌ها به‌صورت «عکس لحظه‌ای» ذخیره می‌شوند (متن سؤال + متن
    پاسخ)، نه فقط شناسه‌ی سؤال. برای همین اگر مدیر بعداً سؤال یا گزینه‌ای را
    ویرایش یا حذف کند، پاسخ‌های قبلی خراب نمی‌شوند. نام کلاس و شعبه هم همان‌طور
    ذخیره می‌شود تا با حذف کلاس، گزارش‌ها و فیلتر «شعبه‌ی مسئول آموزش» بمانند.
    """
    member = models.ForeignKey(
        'members.Member', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='survey_responses', verbose_name='دانش‌پژوه',
    )
    enrollment = models.OneToOneField(
        'class_management.Enrollment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='survey_response', verbose_name='ثبت‌نام',
    )
    class_name = models.CharField('نام کلاس', max_length=200, blank=True)
    branch = models.CharField('شعبه', max_length=100, blank=True)
    # [{"question_id": 3, "question": "...", "kind": "choice", "answer": "خوب"}, ...]
    answers = models.JSONField('پاسخ‌ها', default=list)
    submitted_at = models.DateTimeField('زمان شرکت', auto_now_add=True)

    class Meta:
        verbose_name = 'پاسخ نظرسنجی'
        verbose_name_plural = 'پاسخ‌های نظرسنجی'
        ordering = ['-submitted_at', '-id']

    def __str__(self):
        return f'{self.member} - {self.class_name}'
