from rest_framework import serializers

from core.models import Employee
from .models import BranchDepartment, Class, Department, Enrollment, Lesson, Question, SiteSettings


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
        fields = ['id', 'name']


class LessonSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    branch = serializers.CharField(required=True, allow_blank=False, max_length=100)

    class Meta:
        model = Lesson
        fields = ['id', 'name', 'department', 'department_name', 'branch', 'sessions', 'description']


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
