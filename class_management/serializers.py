# ===== مسیر این فایل در پروژه: class_management/serializers.py (کنار manage.py) =====
from rest_framework import serializers

from core.models import Employee
from .models import (
    BranchDepartment, Class, Department, Enrollment, Lesson, Question, Seminar, SeminarEnrollment, SeminarSession,
    Announcement, SiteSettings, Slide,
)


class SiteSettingsSerializer(serializers.ModelSerializer):
    # public_registration_enabled دیگر یک فیلد دیتابیسی نیست، یک property
    # محاسبه‌شده است (بر اساس registration_mode)؛ برای همین read_only است -
    # ادمین برای تغییرش باید registration_mode را عوض کند
    public_registration_enabled = serializers.BooleanField(read_only=True)

    class Meta:
        model = SiteSettings
        fields = ['registration_mode', 'public_registration_enabled', 'feedback_enabled']


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name', 'class_type']


class LessonSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    branch = serializers.CharField(required=True, allow_blank=False, max_length=100)

    class Meta:
        model = Lesson
        fields = ['id', 'name', 'department', 'department_name', 'class_type', 'branch', 'sessions', 'description']

    def validate(self, attrs):
        # درس و دپارتمانش باید یک «نوع برگزاری» داشته باشند - نمی‌شود درسِ
        # مجازی زیرِ دپارتمانِ حضوری ساخت (یا برعکس)
        department = attrs.get('department', self.instance.department if self.instance else None)
        class_type = attrs.get('class_type', self.instance.class_type if self.instance else 'حضوری')
        if department is not None and department.class_type != class_type:
            raise serializers.ValidationError({'class_type': f'نوع این درس باید «{department.class_type}» باشد (مثل دپارتمانش).'})
        return attrs


class BranchDepartmentSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)

    class Meta:
        model = BranchDepartment
        fields = ['id', 'branch', 'department', 'department_name']


class ClassSerializer(serializers.ModelSerializer):
    """
    نکته: teacher (نیروی انسانی) و department با id فرستاده/خوانده می‌شوند،
    اما برای راحتی نمایش در پنل ادمین، نام‌های خوانا هم اضافه شده‌اند.
    """
    department_name = serializers.CharField(source='department.name', read_only=True)
    lesson_name = serializers.CharField(source='lesson.name', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    prerequisite_name = serializers.CharField(source='prerequisite.name', read_only=True, default=None)
    enrolled_count = serializers.IntegerField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)
    term_order = serializers.IntegerField(source='term.order', read_only=True, default=None)
    branch_province = serializers.SerializerMethodField()
    duration_hours_raw = serializers.SerializerMethodField()

    class Meta:
        model = Class
        fields = [
            'id', 'name', 'lesson', 'lesson_name', 'class_type', 'is_national', 'department', 'department_name', 'branch',
            'branch_province', 'teacher', 'teacher_name', 'term', 'term_order', 'capacity', 'duration_hours_raw', 'start_date', 'day', 'start_time',
            'entry_time', 'gender', 'prerequisite', 'prerequisite_name', 'is_published', 'has_online_exam', 'age_limit_enabled', 'min_age', 'max_age', 'enrolled_count', 'is_full', 'created_at',
        ]

    def validate(self, attrs):
        """
        رده سنی: اگر فعال است، حداقل و حداکثر سن الزامی‌اند، هر دو بین ۰ تا ۱۰۰ و
        حداقل نباید از حداکثر بیشتر باشد. اگر غیرفعال است، هر دو مقدار پاک می‌شوند.
        در ویرایش جزئی (PATCH) که به رده سنی ربطی ندارد (مثلاً فقط «منتشر شود»)
        هیچ‌چیز بررسی/عوض نمی‌شود.
        """
        # «دپارتمان/درسِ مشترک» (حضوری) هم برای کلاس‌های حضوری استفاده می‌شود هم
        # برای کلاس‌های مجازیِ استانی (این دو از «مدیریت دوره و دپارتمان‌ها»، با
        # همان درس/دپارتمانِ مشترک ساخته می‌شوند). فقط کلاس‌های مجازیِ «ملی»
        # (is_national=True) باید از درسِ مجازیِ جداگانه (بخش «دوره‌های مجازی
        # ملی») استفاده کنند؛ نباید از درسِ حضوریِ مشترک برای کلاس ملی استفاده شود.
        if 'lesson' in attrs:
            lesson = attrs['lesson']
            is_national = attrs.get('is_national', self.instance.is_national if self.instance else False)
            if lesson is not None:
                if is_national and lesson.class_type != 'مجازی':
                    raise serializers.ValidationError({'lesson': 'کلاس مجازیِ ملی باید از درسِ بخش «دوره‌های مجازی ملی» استفاده کند.'})
                if not is_national and lesson.class_type != 'حضوری':
                    raise serializers.ValidationError({'lesson': 'این درس مخصوصِ «دوره‌های مجازی ملی» است؛ برای کلاس حضوری/استانی قابل‌استفاده نیست.'})

        age_keys = ('age_limit_enabled', 'min_age', 'max_age')
        if not any(k in attrs for k in age_keys):
            return attrs

        instance = self.instance
        enabled = attrs.get('age_limit_enabled', instance.age_limit_enabled if instance else False)
        min_age = attrs.get('min_age', instance.min_age if instance else None)
        max_age = attrs.get('max_age', instance.max_age if instance else None)

        if not enabled:
            attrs['age_limit_enabled'] = False
            attrs['min_age'] = None
            attrs['max_age'] = None
            return attrs

        if min_age is None or max_age is None:
            raise serializers.ValidationError({'min_age': 'برای رده سنی، حداقل و حداکثر سن را وارد کنید.'})
        if not (0 <= min_age <= 100 and 0 <= max_age <= 100):
            raise serializers.ValidationError({'min_age': 'سن باید عددی بین ۰ تا ۱۰۰ باشد.'})
        if min_age > max_age:
            raise serializers.ValidationError({'min_age': 'حداقل سن نباید از حداکثر سن بیشتر باشد.'})
        return attrs

    def get_duration_hours_raw(self, obj):
        return obj.duration_hours_raw

    def get_branch_province(self, obj):
        from core.models import Branch
        branch = Branch.objects.filter(name=obj.branch).first()
        return branch.province if branch else None

    def get_teacher_name(self, obj):
        return obj.teacher.name if obj.teacher else None


class EnrollmentSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    member_national_id = serializers.CharField(source='member.national_id', read_only=True)
    member_phone = serializers.CharField(source='member.phone', read_only=True)
    is_banned = serializers.SerializerMethodField()
    ban_reason = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    lesson_name = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    term_order = serializers.SerializerMethodField()
    term_year = serializers.SerializerMethodField()
    class_exists = serializers.SerializerMethodField()
    class_is_published = serializers.SerializerMethodField()

    class_type = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            'id', 'class_obj', 'lesson', 'member', 'member_name', 'member_national_id', 'member_phone',
            'is_banned', 'ban_reason', 'enrolled_at', 'score', 'absent',
            'class_name', 'lesson_name', 'department_name', 'branch', 'term_order', 'term_year', 'class_exists', 'class_is_published',
            'class_type', 'duration_hours',
        ]

    def get_class_type(self, obj):
        return obj.class_obj.class_type if obj.class_obj else None

    def get_duration_hours(self, obj):
        return obj.class_obj.duration_hours_raw if obj.class_obj else None

    def validate(self, attrs):
        # اگر «غایب» علامت‌گذاری شود، همیشه نمره صفر می‌شود - حتی اگر فرد
        # مقدار دیگری هم فرستاده باشد (این چک سمت سرور، مستقل از فرانت است)
        if attrs.get('absent'):
            attrs['score'] = 0
        return attrs

    def get_member_name(self, obj):
        return f'{obj.member.user.first_name} {obj.member.user.last_name}'

    def _lesson(self, obj):
        return obj.class_obj.lesson if obj.class_obj else obj.lesson

    def get_class_name(self, obj):
        if obj.class_obj:
            return obj.class_obj.name
        lesson = self._lesson(obj)
        return lesson.name if lesson else '—'

    def get_lesson_name(self, obj):
        lesson = self._lesson(obj)
        return lesson.name if lesson else None

    def get_department_name(self, obj):
        if obj.class_obj:
            return obj.class_obj.department.name
        lesson = self._lesson(obj)
        return lesson.department.name if lesson else None

    def get_branch(self, obj):
        return obj.class_obj.branch if obj.class_obj else None

    def get_term_order(self, obj):
        if obj.class_obj and obj.class_obj.term:
            return obj.class_obj.term.order
        return None

    def get_term_year(self, obj):
        if obj.class_obj and obj.class_obj.term:
            return obj.class_obj.term.year
        return None

    def get_class_exists(self, obj):
        return obj.class_obj is not None

    def get_class_is_published(self, obj):
        return obj.class_obj.is_published if obj.class_obj else None

    def get_is_banned(self, obj):
        return hasattr(obj.member, 'ban')

    def get_ban_reason(self, obj):
        return obj.member.ban.reason if hasattr(obj.member, 'ban') else ''


class QuestionSerializer(serializers.ModelSerializer):
    lesson_name = serializers.CharField(source='lesson.name', read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'lesson', 'lesson_name', 'text', 'options', 'created_at']

    def validate_options(self, value):
        if not isinstance(value, list) or not (2 <= len(value) <= 4):
            raise serializers.ValidationError('تعداد گزینه‌ها باید بین ۲ تا ۴ باشد.')
        correct_count = 0
        for opt in value:
            if not isinstance(opt, dict) or not str(opt.get('text', '')).strip():
                raise serializers.ValidationError('متن همه‌ی گزینه‌ها باید پر شده باشد.')
            if opt.get('is_correct'):
                correct_count += 1
        # می‌تواند یک یا چند گزینه‌ی صحیح داشته باشد (سؤال چندجوابی)، اما
        # نه صفر گزینه (بی‌پاسخ) و نه همه‌ی گزینه‌ها (که دیگر سؤال نیست)
        if correct_count < 1:
            raise serializers.ValidationError('باید حداقل یک گزینه به‌عنوان پاسخ صحیح مشخص شود.')
        if correct_count == len(value):
            raise serializers.ValidationError('همه‌ی گزینه‌ها نمی‌توانند صحیح باشند.')
        return value

    def validate_text(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('متن سؤال نمی‌تواند خالی باشد.')
        return value


class SeminarSessionSerializer(serializers.ModelSerializer):
    """یک «روزِ برگزاری» از سمینار - تاریخ و ساعتِ شروع/پایانِ همان روز."""
    class Meta:
        model = SeminarSession
        fields = ['id', 'date', 'start_time', 'end_time']


class SeminarSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    lesson_name = serializers.CharField(source='lesson.name', read_only=True, default=None)
    teacher_name = serializers.CharField(source='teacher.name', read_only=True, default=None)
    term_order = serializers.IntegerField(source='term.order', read_only=True, default=None)
    term_year = serializers.IntegerField(source='term.year', read_only=True, default=None)
    enrolled_count = serializers.IntegerField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)
    # جلسه‌ها (روزها) همراهِ خودِ سمینار نوشته/خوانده می‌شوند، نه با یک API جدا؛
    # چون معنی ندارد سمیناری بدون هیچ روزی وجود داشته باشد
    sessions = SeminarSessionSerializer(many=True)

    class Meta:
        model = Seminar
        fields = [
            'id', 'name', 'department', 'department_name', 'lesson', 'lesson_name', 'class_type',
            'is_national', 'branch', 'term', 'term_order', 'term_year', 'teacher', 'teacher_name',
            'capacity', 'description', 'is_published', 'enrolled_count', 'is_full', 'sessions',
        ]

    def validate_sessions(self, value):
        if not value:
            raise serializers.ValidationError('حداقل یک روزِ برگزاری لازم است.')
        for session in value:
            if not (session.get('date') or '').strip():
                raise serializers.ValidationError('تاریخِ هر روز باید پر شده باشد.')
            if not (session.get('start_time') or '').strip() or not (session.get('end_time') or '').strip():
                raise serializers.ValidationError('ساعتِ شروع و پایانِ هر روز باید پر شده باشد.')
        return value

    def create(self, validated_data):
        sessions_data = validated_data.pop('sessions')
        seminar = Seminar.objects.create(**validated_data)
        for session_data in sessions_data:
            SeminarSession.objects.create(seminar=seminar, **session_data)
        return seminar

    def update(self, instance, validated_data):
        sessions_data = validated_data.pop('sessions', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        # اگر جلسه‌ها هم فرستاده شده، کل فهرستِ قبلی عوض می‌شود با فهرستِ تازه
        # (ساده‌ترین راهِ درستِ همگام‌سازیِ «چند روزِ قابلِ افزودن/حذف»)
        if sessions_data is not None:
            instance.sessions.all().delete()
            for session_data in sessions_data:
                SeminarSession.objects.create(seminar=instance, **session_data)
        return instance


class SeminarEnrollmentSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    member_national_id = serializers.CharField(source='member.national_id', read_only=True)
    member_phone = serializers.CharField(source='member.phone', read_only=True)
    seminar_name = serializers.CharField(source='seminar.name', read_only=True, default=None)

    class Meta:
        model = SeminarEnrollment
        fields = ['id', 'seminar', 'seminar_name', 'member', 'member_name', 'member_national_id', 'member_phone', 'enrolled_at']

    def get_member_name(self, obj):
        if not obj.member or not obj.member.user:
            return ''
        return f'{obj.member.user.first_name} {obj.member.user.last_name}'.strip()


class SlideSerializer(serializers.ModelSerializer):
    """اسلاید برای پنل ادمین (خواندن و نوشتن)."""
    image_url = serializers.SerializerMethodField()
    mobile_image_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    MAX_IMAGE_BYTES = 5 * 1024 * 1024
    ALLOWED_FORMATS = ('JPEG', 'PNG', 'WEBP')

    class Meta:
        model = Slide
        fields = [
            'id', 'title', 'subtitle', 'image', 'mobile_image', 'image_url', 'mobile_image_url', 'alt_text',
            'button_text', 'link_url', 'open_new_tab', 'text_position', 'text_color', 'overlay',
            'order', 'is_active', 'start_at', 'end_at', 'status', 'created_at',
        ]
        read_only_fields = ['order']
        extra_kwargs = {'image': {'write_only': True, 'required': False}, 'mobile_image': {'write_only': True, 'required': False}}

    def _abs(self, f):
        if not f:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(f.url) if request else f.url

    def get_image_url(self, obj):
        return self._abs(obj.image)

    def get_mobile_image_url(self, obj):
        return self._abs(obj.mobile_image)

    def get_status(self, obj):
        return obj.status()

    def _check_image(self, f):
        # حجم و نوع واقعی تصویر (نه فقط پسوند) بررسی می‌شود
        if f.size > self.MAX_IMAGE_BYTES:
            raise serializers.ValidationError('حجم تصویر نباید بیشتر از ۵ مگابایت باشد.')
        from PIL import Image
        try:
            img = Image.open(f)
            fmt = img.format
            w, h = img.size
            f.seek(0)
        except Exception:
            raise serializers.ValidationError('فایل انتخاب‌شده تصویر معتبر نیست.')
        if fmt not in self.ALLOWED_FORMATS:
            raise serializers.ValidationError('فقط تصویر JPG، PNG یا WebP مجاز است.')
        if w < 400 or h < 150:
            raise serializers.ValidationError('ابعاد تصویر خیلی کوچک است (حداقل ۴۰۰×۱۵۰ پیکسل).')
        return f

    def validate_image(self, value):
        return self._check_image(value)

    def validate_mobile_image(self, value):
        return self._check_image(value) if value else value

    def validate_link_url(self, value):
        value = (value or '').strip()
        # فقط آدرس داخلی (/...) یا http(s) - جلوگیری از javascript: و مشابه
        if value and not (value.startswith('/') and not value.startswith('//')) \
                and not value.lower().startswith(('http://', 'https://')):
            raise serializers.ValidationError('لینک باید با /، http:// یا https:// شروع شود.')
        return value

    def validate_overlay(self, value):
        if value > 80:
            raise serializers.ValidationError('تیرگی حداکثر ۸۰ درصد است.')
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('image'):
            raise serializers.ValidationError({'image': 'انتخاب تصویر الزامی است.'})
        start = attrs.get('start_at', getattr(self.instance, 'start_at', None))
        end = attrs.get('end_at', getattr(self.instance, 'end_at', None))
        if start and end and end <= start:
            raise serializers.ValidationError({'end_at': 'پایان نمایش باید بعد از شروع باشد.'})
        if attrs.get('button_text') and not (attrs.get('link_url', getattr(self.instance, 'link_url', ''))):
            raise serializers.ValidationError({'link_url': 'برای دکمه، لینک را هم وارد کنید.'})
        return attrs


class SlideSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = ['slide_autoplay', 'slide_interval', 'slide_effect', 'slide_show_arrows', 'slide_show_dots']

    def validate_slide_interval(self, value):
        if not (2 <= value <= 20):
            raise serializers.ValidationError('مدت نمایش باید بین ۲ تا ۲۰ ثانیه باشد.')
        return value


class AnnouncementSerializer(serializers.ModelSerializer):
    date = serializers.CharField(source='jalali_date', read_only=True)

    class Meta:
        model = Announcement
        fields = ['id', 'title', 'text', 'branch', 'date', 'created_at']
        read_only_fields = ['created_at']

    def validate_title(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('عنوان اطلاعیه را وارد کنید.')
        return value

    def validate_text(self, value):
        value = (value or '').strip()
        if len(value) > 3000:
            raise serializers.ValidationError('متن اطلاعیه نباید بیشتر از ۳۰۰۰ نویسه باشد.')
        return value

    def validate_branch(self, value):
        # خالی = همه‌ی شعب؛ در غیر این صورت باید دقیقاً نام یک شعبه‌ی ثبت‌شده باشد
        value = (value or '').strip()
        if not value:
            return ''
        from feedback.branches import canonical_branch_name
        name = canonical_branch_name(value)
        if not name:
            raise serializers.ValidationError('شعبه‌ی انتخاب‌شده معتبر نیست.')
        return name
