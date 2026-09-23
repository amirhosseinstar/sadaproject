import json

from rest_framework import serializers

from .models import Branch, Employee, TeacherApplicant


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'province', 'address', 'phone']


class EmployeeSerializer(serializers.ModelSerializer):
    """
    نکته: depts یک JSONField است (لیست دپارتمان‌ها)، بنابراین به‌صورت خودکار
    به/از آرایه‌ی جاوااسکریپت تبدیل می‌شود، نیازی به فیلد سفارشی نیست.
    """
    username = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'name', 'role', 'depts', 'branch', 'phone', 'username',
            'national_id', 'father_name', 'birth_date', 'education_level', 'address', 'photo', 'resume',
        ]

    def get_username(self, obj):
        return obj.user.username if obj.user else None


STAFF_ROLES = ['مدیر آموزش', 'مسئول آموزش']


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

    class Meta:
        model = Employee
        fields = ['id', 'name', 'role', 'branch', 'phone', 'username', 'password', 'has_login']

    def get_has_login(self, obj):
        return obj.user is not None

    def validate_role(self, value):
        if value not in STAFF_ROLES:
            raise serializers.ValidationError('سمت باید «مدیر آموزش» یا «مسئول آموزش» باشد.')
        return value


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
    MAX_PHOTO_SIZE = 100 * 1024        # ۱۰۰ کیلوبایت
    MAX_RESUME_SIZE = 5 * 1024 * 1024  # ۵ مگابایت

    def validate_photo(self, value):
        if value.size > self.MAX_PHOTO_SIZE:
            raise serializers.ValidationError('حجم عکس نباید بیشتر از ۱۰۰ کیلوبایت باشد.')
        return value

    def validate_resume(self, value):
        if value.size > self.MAX_RESUME_SIZE:
            raise serializers.ValidationError('حجم رزومه نباید بیشتر از ۵ مگابایت باشد.')
        return value

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

    def validate_depts(self, value):
        if not value:
            raise serializers.ValidationError('حداقل یک دپارتمان را انتخاب کنید.')
        return value

    def validate_reqtype(self, value):
        if not value:
            raise serializers.ValidationError('حداقل یک نوع همکاری (حضوری/مجازی) را انتخاب کنید.')
        return value
