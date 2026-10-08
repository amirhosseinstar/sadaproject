import re

from rest_framework import serializers

from .branches import canonical_branch_name
from .models import (
    ClassSurvey, ClassSurveyQuestion, Feedback, GeneralSurvey, GeneralSurveyQuestion,
    effective_questions,
)

# رقم‌های فارسی/عربی -> انگلیسی (همان کاری که تابع normalizeDigits در login.html
# می‌کند؛ اگر شماره از جای دیگری کپی شده باشد ممکن است رقم فارسی یا
# کاراکتر نامرئی همراهش باشد و نباید به‌خاطر آن رد شود).
_DIGIT_MAP = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
# کاراکترهای نامرئی رایج (نیم‌فاصله، علامت‌های جهت‌دهی متن، فاصله‌ی صفر و ...)
_INVISIBLE_RE = re.compile('[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00a0\\s]')

MAX_MESSAGE_LENGTH = 2000


class FeedbackCreateSerializer(serializers.ModelSerializer):
    """
    اعتبارسنجی فرم سایت. فقط چهار فیلد از بیرون پذیرفته می‌شوند؛ فرستنده
    (از روی کاربر واردشده)، وضعیت و فیلدهای پاسخ را هیچ‌وقت نمی‌شود از این
    مسیر تعیین کرد.
    """
    message = serializers.CharField(max_length=MAX_MESSAGE_LENGTH, trim_whitespace=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    branch = serializers.CharField(max_length=100, required=True, allow_blank=True)

    class Meta:
        model = Feedback
        fields = ['kind', 'phone', 'branch', 'message']

    def validate_phone(self, value):
        cleaned = _INVISIBLE_RE.sub('', value).translate(_DIGIT_MAP)
        if not cleaned:
            return ''
        if not re.fullmatch(r'\d{10,12}', cleaned):
            raise serializers.ValidationError('شماره تماس باید فقط عدد و بین ۱۰ تا ۱۲ رقم باشد.')
        return cleaned

    def validate_branch(self, value):
        value = value.strip()
        if not value:
            # انتخاب شعبه برای ثبت انتقاد/پیشنهاد اجباری است
            raise serializers.ValidationError('انتخاب شعبه الزامی است.')
        # شعبه باید یکی از شعب واقعی باشد؛ نام استاندارد ذخیره می‌شود تا فیلتر
        # «فقط پیام‌های شعبه‌ی خودم» برای مسئول آموزش دقیق کار کند
        canonical = canonical_branch_name(value)
        if canonical is None:
            raise serializers.ValidationError('شعبه‌ی انتخاب‌شده معتبر نیست.')
        return canonical


class FeedbackSerializer(serializers.ModelSerializer):
    """
    نمایش کامل یک مورد برای پنل مدیر/مسئول آموزش (فقط خواندنی).
    فیلد sender همه‌ی اطلاعات فرستنده را می‌دهد (برای پنجره‌ی «اطلاعات
    فرستنده» و دکمه‌ی «سوابق آموزشی»)؛ اگر حساب فرستنده حذف شده باشد null است.
    """
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    sender_name = serializers.SerializerMethodField()
    sender = serializers.SerializerMethodField()

    class Meta:
        model = Feedback
        fields = [
            'id', 'kind', 'kind_display', 'phone', 'branch', 'message',
            'status', 'status_display',
            'replier_name', 'reply_text', 'replied_at', 'created_at',
            'sender_name', 'sender',
        ]
        read_only_fields = fields

    def get_sender_name(self, obj):
        if obj.member is None:
            return ''
        user = obj.member.user
        return f'{user.first_name} {user.last_name}'.strip()

    def get_sender(self, obj):
        member = obj.member
        if member is None:
            return None
        ban = getattr(member, 'ban', None)
        return {
            'first_name': member.user.first_name,
            'last_name': member.user.last_name,
            'father_name': member.father_name,
            'birth_date': member.birth_date,
            'national_id': member.national_id,
            'membership_code': member.membership_code,
            'phone': member.phone,
            'province': member.province,
            'branch': member.branch,
            'membership_since': member.created_at,
            'card_expires_at': member.card_expires_at,
            'is_membership_valid': member.is_membership_valid,
            'is_banned': ban is not None,
            'ban_reason': ban.reason if ban is not None else '',
        }


class FeedbackReplySerializer(serializers.Serializer):
    """ورودی ثبت پاسخ: نام مسئول + متن پاسخ (هر دو الزامی)."""
    replier_name = serializers.CharField(max_length=100, trim_whitespace=True)
    reply_text = serializers.CharField(max_length=MAX_MESSAGE_LENGTH, trim_whitespace=True)


# ---------------------------------------------------------------------------
# نظرسنجی کلی کلاس
# ---------------------------------------------------------------------------
MAX_OPTIONS = 10   # حداکثر گزینه‌ی یک سؤال تستی
MIN_OPTIONS = 2    # حداقل گزینه‌ی یک سؤال تستی


class ClassSurveyQuestionSerializer(serializers.ModelSerializer):
    """
    اعتبارسنجی یک سؤال. قاعده‌ها:
      - سؤال تستی: ۲ تا ۱۰ گزینه‌ی غیرخالی و غیرتکراری
      - سؤال تشریحی: گزینه ندارد (اگر فرستاده شود نادیده و خالی می‌شود)
    ترتیب (order) از بیرون قابل تعیین نیست؛ سرور خودش می‌گذارد (و فقط از مسیر
    reorder عوض می‌شود).
    """
    text = serializers.CharField(max_length=500, trim_whitespace=True)
    options = serializers.ListField(
        child=serializers.CharField(max_length=200, trim_whitespace=True),
        required=False,
    )

    class Meta:
        model = ClassSurveyQuestion
        fields = ['id', 'text', 'kind', 'options', 'order']
        read_only_fields = ['id', 'order']

    def validate(self, attrs):
        # در ویرایش جزئی (PATCH)، مقدار فرستاده‌نشده از خود سؤال خوانده می‌شود
        instance = self.instance
        kind = attrs.get('kind', instance.kind if instance else ClassSurveyQuestion.KIND_CHOICE)
        options = attrs.get('options', list(instance.options) if instance else [])

        if kind == ClassSurveyQuestion.KIND_TEXT:
            attrs['options'] = []
            return attrs

        if len(options) < MIN_OPTIONS:
            raise serializers.ValidationError({'options': f'سؤال تستی حداقل {MIN_OPTIONS} گزینه لازم دارد.'})
        if len(options) > MAX_OPTIONS:
            raise serializers.ValidationError({'options': f'سؤال تستی حداکثر {MAX_OPTIONS} گزینه می‌تواند داشته باشد.'})
        if len(set(options)) != len(options):
            raise serializers.ValidationError({'options': 'گزینه‌ها نباید تکراری باشند.'})
        attrs['options'] = options
        return attrs


class ClassSurveySerializer(serializers.ModelSerializer):
    """نظرسنجی کلی به‌همراه سؤال‌هایش (به ترتیب). فقط عنوان و توضیحات قابل ویرایش‌اند."""
    title = serializers.CharField(max_length=200, trim_whitespace=True)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    questions = ClassSurveyQuestionSerializer(many=True, read_only=True)

    class Meta:
        model = ClassSurvey
        fields = ['title', 'description', 'questions', 'updated_at']
        read_only_fields = ['updated_at']


MAX_TEXT_ANSWER_LENGTH = 2000


def snapshot_answers(questions, raw_answers):
    """
    پاسخ‌های فرستاده‌شده را با سؤال‌ها تطبیق می‌دهد و «عکس لحظه‌ای» آماده‌ی ذخیره برمی‌گرداند.
    (هم برای نظرسنجی کلاسی و هم برای نظرسنجی کلی؛ questions اشیایی با id/text/kind/options‌اند.)
      - به هر سؤال «تستی» باید پاسخ داده شود و پاسخ دقیقاً یکی از گزینه‌هایش باشد
      - سؤال «تشریحی» اختیاری است و حداکثر ۲۰۰۰ کاراکتر
      - شناسه‌ی سؤالِ ناموجود یا تکراری رد می‌شود
    """
    by_id = {}
    for item in raw_answers:
        try:
            qid = int(item.get('question_id'))
        except (TypeError, ValueError):
            raise serializers.ValidationError({'detail': 'شناسه‌ی سؤال نامعتبر است.'})
        if qid in by_id:
            raise serializers.ValidationError({'detail': 'پاسخ یک سؤال بیش از یک‌بار فرستاده شده است.'})
        by_id[qid] = item.get('answer')

    valid_ids = {q.id for q in questions}
    if set(by_id) - valid_ids:
        raise serializers.ValidationError({'detail': 'سؤالی که فرستاده شده در نظرسنجی وجود ندارد.'})

    snapshot = []
    for q in questions:
        raw = by_id.get(q.id)
        answer = raw.strip() if isinstance(raw, str) else ''
        if q.kind == 'choice':
            if not answer:
                raise serializers.ValidationError({'detail': f'لطفاً به سؤال «{q.text}» پاسخ دهید.'})
            if answer not in q.options:
                raise serializers.ValidationError({'detail': f'پاسخ سؤال «{q.text}» معتبر نیست.'})
        elif len(answer) > MAX_TEXT_ANSWER_LENGTH:
            raise serializers.ValidationError({'detail': f'پاسخ تشریحی حداکثر {MAX_TEXT_ANSWER_LENGTH} کاراکتر می‌تواند باشد.'})
        snapshot.append({'question_id': q.id, 'question': q.text, 'kind': q.kind, 'answer': answer})
    return snapshot


class ClassSurveySubmitSerializer(serializers.Serializer):
    """
    ورودی شرکت در نظرسنجی:
        {"enrollment_id": 5, "answers": [{"question_id": 1, "answer": "خوب"}, ...]}

    قاعده‌ها (همه سمت سرور، مستقل از فرانت‌اند):
      - به هر سؤال «تستی» باید پاسخ داده شود و پاسخ باید دقیقاً یکی از گزینه‌های
        همان سؤال باشد (نه هر متن دلخواه)
      - پاسخ سؤال «تشریحی» اختیاری است (خالی هم قبول می‌شود)، حداکثر ۲۰۰۰ کاراکتر
      - شناسه‌ی سؤالِ ناموجود یا تکراری رد می‌شود
    خروجی validated_data['answers'] لیست آماده‌ی ذخیره (عکس لحظه‌ای) است.
    """
    # دقیقاً یکی از این دو: ثبت‌نام کلاس یا ثبت‌نام سمینار/کارگاه
    enrollment_id = serializers.IntegerField(required=False)
    seminar_enrollment_id = serializers.IntegerField(required=False)
    answers = serializers.ListField(child=serializers.DictField(), allow_empty=True)

    def validate(self, attrs):
        if bool(attrs.get('enrollment_id')) == bool(attrs.get('seminar_enrollment_id')):
            raise serializers.ValidationError({'detail': 'دقیقاً یکی از enrollment_id یا seminar_enrollment_id لازم است.'})
        if attrs.get('seminar_enrollment_id'):
            # سمینار/کارگاه: سؤال‌ها همان «قالب کلی» است
            questions = effective_questions(None)
        else:
            # سؤال‌ها بر اساس «کلاسِ همین ثبت‌نام» تعیین می‌شود: سؤال‌های اختصاصی آن کلاس، وگرنه قالب مشترک.
            # (مالکیت ثبت‌نام را خودِ view بعداً چک می‌کند؛ اینجا فقط سؤال‌های درست را پیدا می‌کنیم.)
            from class_management.models import Enrollment
            enrollment = Enrollment.objects.select_related('class_obj').filter(pk=attrs['enrollment_id']).first()
            klass = enrollment.class_obj if enrollment else None
            questions = effective_questions(klass)
        if not questions:
            raise serializers.ValidationError({'detail': 'نظرسنجی هنوز سؤالی ندارد.'})
        attrs['answers'] = snapshot_answers(questions, attrs['answers'])
        return attrs


# ---------------------------------------------------------------------------
# سؤال اختصاصی یک کلاس
# ---------------------------------------------------------------------------
class ClassSpecificQuestionSerializer(ClassSurveyQuestionSerializer):
    """
    سؤال اختصاصی نظرسنجیِ یک کلاس (همان قاعده‌های سؤال قالب).
    class_id فقط موقع «ساخت» لازم است؛ بعد از ساخته شدن، سؤال به کلاس دیگری منتقل نمی‌شود.
    """
    class_id = serializers.IntegerField(write_only=True, required=False)

    class Meta(ClassSurveyQuestionSerializer.Meta):
        fields = ['id', 'text', 'kind', 'options', 'order', 'class_id']
        read_only_fields = ['id', 'order']

    def validate(self, attrs):
        class_id = attrs.pop('class_id', None)
        if self.instance is None:
            from class_management.models import Class
            klass = Class.objects.filter(pk=class_id).first() if class_id else None
            if klass is None:
                raise serializers.ValidationError({'class_id': 'کلاس مشخص نشده یا پیدا نشد.'})
            attrs['class_obj'] = klass            # ساخت: سؤال به همین کلاس وصل می‌شود
        # در ویرایش، انتقال سؤال به کلاس دیگر مجاز نیست (class_id نادیده گرفته می‌شود)
        return super().validate(attrs)


# ---------------------------------------------------------------------------
# نظرسنجی‌های کلی (دلخواه)
# ---------------------------------------------------------------------------
class GeneralQuestionInputSerializer(serializers.Serializer):
    """یک سؤالِ ورودیِ نظرسنجی کلی (همان قاعده‌ی گزینه‌ها: تستی ۲ تا ۱۰ گزینه‌ی یکتا، تشریحی بدون گزینه)."""
    id = serializers.IntegerField(required=False)
    text = serializers.CharField(max_length=500, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=[GeneralSurveyQuestion.KIND_CHOICE, GeneralSurveyQuestion.KIND_TEXT])
    options = serializers.ListField(
        child=serializers.CharField(max_length=200, trim_whitespace=True), required=False,
    )

    def validate(self, attrs):
        if attrs['kind'] == GeneralSurveyQuestion.KIND_TEXT:
            attrs['options'] = []
            return attrs
        options = attrs.get('options', [])
        if len(options) < MIN_OPTIONS:
            raise serializers.ValidationError({'options': f'سؤال تستی حداقل {MIN_OPTIONS} گزینه لازم دارد.'})
        if len(options) > MAX_OPTIONS:
            raise serializers.ValidationError({'options': f'سؤال تستی حداکثر {MAX_OPTIONS} گزینه می‌تواند داشته باشد.'})
        if any(not o for o in options):
            raise serializers.ValidationError({'options': 'گزینه‌ی خالی مجاز نیست.'})
        if len(set(options)) != len(options):
            raise serializers.ValidationError({'options': 'گزینه‌ها نباید تکراری باشند.'})
        return attrs


class GeneralQuestionOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralSurveyQuestion
        fields = ['id', 'text', 'kind', 'options', 'order']


class GeneralSurveySerializer(serializers.ModelSerializer):
    """
    نظرسنجی کلی همراه سؤال‌هایش. موقع ساخت/ویرایش، کل فهرست سؤال‌ها فرستاده می‌شود:
      - سؤالی که id دارد و در همین نظرسنجی هست ← ویرایش می‌شود (پاسخ‌های قبلی‌اش سالم می‌ماند)
      - سؤال بدون id ← جدید
      - سؤالی که در فهرست نیست ← حذف می‌شود
    ترتیب سؤال‌ها همان ترتیب فهرست است.
    """
    title = serializers.CharField(max_length=200, trim_whitespace=True)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    questions = GeneralQuestionInputSerializer(many=True, write_only=True, required=False)
    question_list = GeneralQuestionOutSerializer(source='questions', many=True, read_only=True)
    question_count = serializers.SerializerMethodField()
    response_count = serializers.SerializerMethodField()

    class Meta:
        model = GeneralSurvey
        fields = ['id', 'title', 'description', 'is_active', 'created_at', 'updated_at',
                  'questions', 'question_list', 'question_count', 'response_count']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_question_count(self, obj):
        return len(obj.questions.all())

    def get_response_count(self, obj):
        # تعداد شرکت‌کنندگان فقط برای مدیر/مسئول آموزش نمایش داده می‌شود (نه برای دانش‌پژوه)
        request = self.context.get('request')
        from core.permissions import staff_role
        if request is None or staff_role(request.user) is None:
            return None
        return obj.responses.count()

    def validate_questions(self, value):
        if len(value) > 50:
            raise serializers.ValidationError('حداکثر ۵۰ سؤال در هر نظرسنجی مجاز است.')
        return value

    def _save_questions(self, survey, items):
        keep = set()
        existing = {q.id: q for q in survey.questions.all()}
        for position, item in enumerate(items, start=1):
            q = existing.get(item.get('id'))
            if q is None:
                q = GeneralSurveyQuestion(survey=survey)
            q.text, q.kind, q.options, q.order = item['text'], item['kind'], item.get('options', []), position
            q.save()
            keep.add(q.id)
        survey.questions.exclude(id__in=keep).delete()

    def create(self, validated_data):
        from django.db import transaction
        items = validated_data.pop('questions', [])
        with transaction.atomic():
            survey = GeneralSurvey.objects.create(**validated_data)
            self._save_questions(survey, items)
        return survey

    def update(self, instance, validated_data):
        from django.db import transaction
        items = validated_data.pop('questions', None)
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.save()
            if items is not None:
                self._save_questions(instance, items)
        return instance


class GeneralSurveySubmitSerializer(serializers.Serializer):
    """ورودی شرکت در نظرسنجی کلی: {"answers": [{"question_id": 1, "answer": "خوب"}, ...]}"""
    answers = serializers.ListField(child=serializers.DictField(), allow_empty=True)
