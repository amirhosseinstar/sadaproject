# ===== مسیر این فایل در پروژه: core/serializers.py (کنار manage.py) =====
import json
import re

from rest_framework import serializers

from sada_project.utils import parse_jalali_date, to_english_digits

from .models import Branch, Employee, TeacherApplicant

# ---------------------------------------------------------------------------
# اعتبارسنجیِ مشترکِ فیلدهای مدرس/متقاضی/متصدی (سمت سرور)
# چک‌های جاوااسکریپتِ صفحه‌ها با زدنِ مستقیم به API (یا غیرفعال‌کردن JS) دور زده می‌شوند؛ پس قواعد
# واقعی اینجاست و هر سه سریالایزر (متقاضی، مدرسِ تأییدشده، متصدی) از همین توابع استفاده می‌کنند.
# ---------------------------------------------------------------------------
EDUCATION_LEVELS = ['سیکل', 'دیپلم', 'کاردانی', 'کارشناسی', 'کارشناسی ارشد', 'دکتری']
TEACHING_TYPES = ['حضوری', 'مجازی']
MAX_PHOTO_SIZE = 100 * 1024        # ۱۰۰ کیلوبایت
MAX_RESUME_SIZE = 5 * 1024 * 1024  # ۵ مگابایت


def clean_mobile(value):
    """شماره موبایل ۱۱ رقمی که با ۰۹ شروع شود (ارقام فارسی به انگلیسی تبدیل می‌شود)."""
    cleaned = to_english_digits(value).strip().replace(' ', '')
    if not re.fullmatch(r'09\d{9}', cleaned):
        raise serializers.ValidationError('شماره تماس باید یک شماره موبایل ۱۱ رقمی باشد (مثل ۰۹۱۲۳۴۵۶۷۸۹).')
    return cleaned


def clean_national_id(value, allow_blank=False):
    """کد ملی: دقیقاً ۱۰ رقم."""
    cleaned = to_english_digits(value).strip()
    if not cleaned and allow_blank:
        return ''
    if not re.fullmatch(r'\d{10}', cleaned):
        raise serializers.ValidationError('کد ملی باید دقیقاً ۱۰ رقم باشد.')
    return cleaned


def clean_birth_date(value):
    """تاریخ تولد شمسیِ معتبر و نه در آینده (مثل ۱۳۷۰/۰۵/۱۲). خالی مجاز است (مدرسینِ قدیمی)."""
    text = (value or '').strip()
    if text and parse_jalali_date(text) is None:
        raise serializers.ValidationError('تاریخ تولد نامعتبر است؛ یک تاریخ شمسیِ واقعی و نه در آینده وارد کنید (مثل ۱۳۷۰/۰۵/۱۲).')
    return text


def clean_education(value):
    text = (value or '').strip()
    if text and text not in EDUCATION_LEVELS:
        raise serializers.ValidationError('میزان تحصیلات باید یکی از گزینه‌های فهرست باشد.')
    return text


def clean_string_list(value, label, allowed=None):
    """لیستی از رشته‌های غیرخالی (نه یک رشته‌ی تکی)؛ تکراری‌ها حذف می‌شوند. allowed: مقادیر مجاز (اختیاری)."""
    if not isinstance(value, list):
        raise serializers.ValidationError(f'{label} باید یک فهرست باشد.')
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise serializers.ValidationError(f'{label} فقط می‌تواند شامل نام‌های معتبر باشد.')
        item = item.strip()
        if allowed is not None and item not in allowed:
            raise serializers.ValidationError(f'«{item}» در {label} مجاز نیست.')
        if item not in items:
            items.append(item)
    return items


def _head_bytes(upload, count=12):
    """چند بایتِ ابتدای فایل آپلودی را می‌خواند و اشاره‌گر را به اول برمی‌گرداند."""
    upload.seek(0)
    head = upload.read(count)
    upload.seek(0)
    return head


def check_photo_file(upload):
    """عکس: فقط JPG/PNG/WebP (هم پسوند و هم محتوای واقعیِ فایل)، حداکثر ۱۰۰ کیلوبایت."""
    if upload is None:
        return upload
    if upload.size > MAX_PHOTO_SIZE:
        raise serializers.ValidationError('حجم عکس نباید بیشتر از ۱۰۰ کیلوبایت باشد.')
    name = (upload.name or '').lower()
    head = _head_bytes(upload)
    is_jpeg = head.startswith(b'\xff\xd8\xff') and name.endswith(('.jpg', '.jpeg'))
    is_png = head.startswith(b'\x89PNG\r\n\x1a\n') and name.endswith('.png')
    is_webp = head[:4] == b'RIFF' and head[8:12] == b'WEBP' and name.endswith('.webp')
    if not (is_jpeg or is_png or is_webp):
        raise serializers.ValidationError('عکس باید یک فایل واقعیِ JPG، PNG یا WebP باشد.')
    return upload


def check_resume_file(upload):
    """رزومه: فقط PDF/DOC/DOCX (هم پسوند و هم محتوای واقعیِ فایل)، حداکثر ۵ مگابایت."""
    if upload is None:
        return upload
    if upload.size > MAX_RESUME_SIZE:
        raise serializers.ValidationError('حجم رزومه نباید بیشتر از ۵ مگابایت باشد.')
    name = (upload.name or '').lower()
    head = _head_bytes(upload)
    is_pdf = head.startswith(b'%PDF') and name.endswith('.pdf')
    is_docx = head.startswith(b'PK\x03\x04') and name.endswith('.docx')
    is_doc = head.startswith(b'\xd0\xcf\x11\xe0') and name.endswith('.doc')
    if not (is_pdf or is_docx or is_doc):
        raise serializers.ValidationError('رزومه باید یک فایل واقعیِ PDF یا Word (doc/docx) باشد.')
    return upload


# استان‌های کشور (همان نام‌هایی که در جدول شعب و استانِ اعضا استفاده می‌شود)؛ چک استانِ ثبت‌نام
# (کلاس ↔ دانش‌پژوه) با برابری دقیقِ متن انجام می‌شود، پس املای استان باید یکسان باشد.
IRAN_PROVINCES = [
    'آذربایجان شرقی', 'آذربایجان غربی', 'اردبیل', 'اصفهان', 'البرز', 'ایلام', 'بوشهر', 'تهران',
    'چهارمحال و بختیاری', 'خراسان جنوبی', 'خراسان رضوی', 'خراسان شمالی', 'خوزستان', 'زنجان', 'سمنان',
    'سیستان و بلوچستان', 'فارس', 'قزوین', 'قم', 'کردستان', 'کرمان', 'کرمانشاه', 'کهگیلویه و بویراحمد',
    'گلستان', 'گیلان', 'لرستان', 'مازندران', 'مرکزی', 'هرمزگان', 'همدان', 'یزد',
]


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'province', 'address', 'phone']

    def validate_province(self, value):
        # بدون استان، چک «استان کلاس با استان دانش‌پژوه» برای این شعبه بی‌صدا غیرفعال می‌شود
        value = (value or '').strip()
        if value not in IRAN_PROVINCES:
            raise serializers.ValidationError('استان شعبه را از لیست انتخاب کنید.')
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('province'):
            raise serializers.ValidationError({'province': 'استان شعبه را انتخاب کنید.'})
        return attrs


class EmployeeSerializer(serializers.ModelSerializer):
    """
    نکته: depts یک JSONField است (لیست دپارتمان‌ها)، بنابراین به‌صورت خودکار
    به/از آرایه‌ی جاوااسکریپت تبدیل می‌شود، نیازی به فیلد سفارشی نیست.
    """
    username = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'name', 'role', 'depts', 'reqtype', 'branch', 'phone', 'username',
            'national_id', 'father_name', 'birth_date', 'education_level', 'address', 'photo', 'resume',
        ]
        # امنیت: «سمت» از این مسیر هرگز قابل تغییر نیست (جلوگیری از ارتقای مدرس به مدیر)
        read_only_fields = ['role']

    def get_username(self, obj):
        return obj.user.username if obj.user else None

    # اعتبارسنجی سمت سرور (قبلاً کد ملیِ «abc»، تلفنِ «xyz»، تاریخ تولدِ آینده، شعبه‌ی جعلی،
    # دپارتمان‌ها به‌صورت رشته‌ی تکی و رزومه‌ی .exe پذیرفته می‌شد)
    def validate_phone(self, value):
        return clean_mobile(value)

    def validate_national_id(self, value):
        return clean_national_id(value, allow_blank=True)     # مدرسینِ قدیمی ممکن است کد ملی نداشته باشند

    def validate_birth_date(self, value):
        return clean_birth_date(value)

    def validate_education_level(self, value):
        return clean_education(value)

    def validate_depts(self, value):
        return clean_string_list(value, 'دپارتمان‌ها')

    def validate_reqtype(self, value):
        return clean_string_list(value, 'نوع تدریس', allowed=TEACHING_TYPES)

    def validate_branch(self, value):
        return _canonical_branch_or_error(value)

    def validate_photo(self, value):
        return check_photo_file(value)

    def validate_resume(self, value):
        return check_resume_file(value)


STAFF_ROLES = ['مدیر آموزش', 'مسئول آموزش']


def _canonical_branch_or_error(value):
    """
    شعبه باید یکی از شعبِ واقعیِ جدول Branch باشد؛ نام استاندارد همان جدول ذخیره می‌شود (نه متن آزاد)،
    تا شعبه‌ی جعلی/غلط‌املایی ثبت نشود و فیلترهای «مسئول فقط شعبه‌ی خودش» دقیق کار کنند.
    """
    from feedback.branches import canonical_branch_name
    canonical = canonical_branch_name(value)
    if canonical is None:
        raise serializers.ValidationError('شعبه‌ی انتخاب‌شده در لیست شعب وجود ندارد.')
    return canonical


class StaffSerializer(serializers.ModelSerializer):
    """
    متصدیان (مدیر آموزش/مسئول آموزش) - بر خلاف مدرس، اینجا افزودن مستقیم
    مجاز است (مفهوم «تأیید درخواست» برای این سمت‌ها معنی ندارد). فقط این
    دو سمت را قبول می‌کند - حتی اگر کسی تلاش کند role را «مدرس» بفرستد،
    رد می‌شود، تا این مسیر هیچ‌وقت جایگزین جریان تأیید مدرس نشود.
    """
    username = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_login = serializers.SerializerMethodField()
    # برای پنل: دکمه‌های ویرایش/حذف/دسترسی فقط وقتی نشان داده شوند که سرور هم اجازه بدهد
    can_manage = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ['id', 'name', 'role', 'branch', 'phone', 'username', 'password', 'has_login',
                  'can_manage', 'can_delete']

    def get_has_login(self, obj):
        return obj.user is not None

    def _is_self(self, obj):
        request = self.context.get('request')
        return bool(request and obj.user_id is not None and obj.user_id == request.user.pk)

    def get_can_manage(self, obj):
        # مدیرانِ آموزش نمی‌توانند اطلاعات/مجوزِ یکدیگر را تغییر دهند (فقط خودِ شخص برای حساب خودش)
        request = self.context.get('request')
        if obj.role != 'مدیر آموزش':
            return True
        return bool(request and (request.user.is_superuser or self._is_self(obj)))

    def get_can_delete(self, obj):
        # حذف: هرگز حساب خود؛ و هرگز مدیرِ دیگر (مگر ابرکاربر سیستم)
        request = self.context.get('request')
        if self._is_self(obj):
            return False
        if obj.role == 'مدیر آموزش':
            return bool(request and request.user.is_superuser)
        return True

    def validate_name(self, value):
        # نام و نام خانوادگی: فقط حروف (فارسی/انگلیسی) و فاصله؛ بدون عدد و نماد، حداکثر ۶۰ کاراکتر
        value = re.sub(r'\s+', ' ', (value or '').strip())
        if not 2 <= len(value) <= 60:
            raise serializers.ValidationError('نام و نام خانوادگی باید بین ۲ تا ۶۰ کاراکتر باشد.')
        if not re.fullmatch(r'[A-Za-z\u0600-\u06FF\u200c ]+', value) or re.search(r'[0-9\u06F0-\u06F9\u0660-\u0669]', value):
            raise serializers.ValidationError('نام و نام خانوادگی فقط می‌تواند شامل حروف باشد (بدون عدد و نماد).')
        return value

    def validate_role(self, value):
        if value not in STAFF_ROLES:
            raise serializers.ValidationError('سمت باید «مدیر آموزش» یا «مسئول آموزش» باشد.')
        return value

    def validate_branch(self, value):
        return _canonical_branch_or_error(value)

    def validate_phone(self, value):
        return clean_mobile(value)


class DeptListField(serializers.Field):
    """
    فیلد لیست دپارتمان‌ها (مثل ["کامپیوتر","هنر"]).

    وقتی درخواست از نوع JSON عادی باشد، یک آرایه‌ی جاوااسکریپت معمولی است.
    اما وقتی فرم شامل فایل (عکس/رزومه) هم باشد، فرانت‌اند باید از
    multipart/form-data استفاده کند که در آن آرایه به‌صورت رشته‌ی JSON
    فرستاده می‌شود؛ این فیلد هر دو حالت را قبول می‌کند.
    """
    def to_internal_value(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, str):
            if not data.strip():
                return []
            try:
                parsed = json.loads(data)
            except ValueError:
                raise serializers.ValidationError('depts باید یک آرایه یا رشته‌ی JSON معتبر باشد.')
            if not isinstance(parsed, list):
                raise serializers.ValidationError('depts باید یک آرایه باشد.')
            return parsed
        raise serializers.ValidationError('فرمت depts نامعتبر است.')

    def to_representation(self, value):
        return value or []


class TeacherApplicantSerializer(serializers.ModelSerializer):
    """
    درخواست همکاری مدرس متقاضی.

    طبق تصمیم پروژه، همه‌ی فیلدها الزامی‌اند به‌جز «توضیحات متقاضی».
    نام‌کاربری/رمز عبور دیگر بخشی از این فرم نیستند - آن‌ها فقط لحظه‌ی
    تأیید (approve) از ادمین/مسئول آموزش پرسیده می‌شوند (نگاه کنید به
    core/services.py::approve_teacher_applicant).
    """
    name = serializers.SerializerMethodField()
    depts = DeptListField()
    reqtype = DeptListField()
    branch = serializers.CharField(allow_blank=False, max_length=100)
    national_id = serializers.CharField(allow_blank=False, max_length=10)
    address = serializers.CharField(allow_blank=False, max_length=300)
    photo = serializers.FileField(required=True)
    resume = serializers.FileField(required=True)

    # نکته‌ی مهم: چک حجم فایل توی جاوااسکریپت (teacher-registration.html)
    # به‌تنهایی کافی نیست - چون با غیرفعال‌کردن جاوااسکریپت یا زدن مستقیم
    # به همین API (مثلاً با Postman) به‌سادگی دور زده می‌شود. اعتبارسنجی
    # واقعی و غیرقابل‌دورزدن همین‌جا، سمت سرور، انجام می‌شود.
    def validate_photo(self, value):
        return check_photo_file(value)

    def validate_resume(self, value):
        return check_resume_file(value)

    def validate_phone(self, value):
        return clean_mobile(value)

    def validate_national_id(self, value):
        return clean_national_id(value)

    def validate_birth_date(self, value):
        return clean_birth_date(value)

    def validate_education_level(self, value):
        return clean_education(value)

    class Meta:
        model = TeacherApplicant
        fields = [
            'id', 'first_name', 'last_name', 'name', 'depts', 'reqtype', 'regtype',
            'branch', 'phone', 'national_id', 'education_level', 'father_name', 'birth_date', 'address',
            'photo', 'resume', 'message', 'status', 'created_at',
        ]
        read_only_fields = ['status', 'created_at']

    def get_name(self, obj):
        return f'{obj.first_name} {obj.last_name}'.strip()

    def validate_branch(self, value):
        return _canonical_branch_or_error(value)

    def validate_depts(self, value):
        value = clean_string_list(value, 'دپارتمان‌ها')
        if not value:
            raise serializers.ValidationError('حداقل یک دپارتمان را انتخاب کنید.')
        return value

    def validate_reqtype(self, value):
        value = clean_string_list(value, 'نوع همکاری', allowed=TEACHING_TYPES)
        if not value:
            raise serializers.ValidationError('حداقل یک نوع همکاری (حضوری/مجازی) را انتخاب کنید.')
        return value
