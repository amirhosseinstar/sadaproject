from rest_framework import serializers

from .models import AcademicTerm, CalendarDocument


class DatePointSerializer(serializers.Serializer):
    m = serializers.IntegerField(min_value=1, max_value=12)
    d = serializers.IntegerField(min_value=1, max_value=31)
    yearOffset = serializers.IntegerField(required=False)


class DateRangeSerializer(serializers.Serializer):
    start = DatePointSerializer()
    end = DatePointSerializer()


class AcademicTermSerializer(serializers.ModelSerializer):
    """
    برای مدیریت (ساخت/ویرایش/حذف) یک دوره از پنل ادمین استفاده می‌شود.
    """
    class Meta:
        model = AcademicTerm
        fields = [
            'id', 'year', 'order', 'code',
            'registration', 'classes', 'move', 'exam',
            'is_active',
        ]
        read_only_fields = ['code']


class TermAsPeriodSerializer(serializers.Serializer):
    """
    یک AcademicTerm را دقیقاً با همان شکلی که فرانت‌اند (سدا.html) انتظار
    دارد بازمی‌گرداند - یعنی همان ساختار CALENDAR_DATA.periods[i] که قبلاً
    به‌صورت ثابت در جاوااسکریپت نوشته شده بود. به همین دلیل با تغییر بک‌اند،
    نیازی به تغییر منطق رندر جدول در فرانت‌اند نیست.
    """
    period = serializers.CharField(source='code')
    regStart = serializers.SerializerMethodField()
    regEnd = serializers.SerializerMethodField()
    classStart = serializers.SerializerMethodField()
    classEnd = serializers.SerializerMethodField()
    moveStart = serializers.SerializerMethodField()
    moveEnd = serializers.SerializerMethodField()
    examStart = serializers.SerializerMethodField()
    examEnd = serializers.SerializerMethodField()

    def get_regStart(self, obj):
        return obj.registration['start']

    def get_regEnd(self, obj):
        return obj.registration['end']

    def get_classStart(self, obj):
        return obj.classes['start']

    def get_classEnd(self, obj):
        return obj.classes['end']

    def get_moveStart(self, obj):
        return obj.move['start']

    def get_moveEnd(self, obj):
        return obj.move['end']

    def get_examStart(self, obj):
        return obj.exam['start']

    def get_examEnd(self, obj):
        return obj.exam['end']


class CalendarDocumentSerializer(serializers.ModelSerializer):
    """فایل PDF تقویم آموزشی یک سال - برای آپلود در پنل ادمین و دانلود در سایت."""

    class Meta:
        model = CalendarDocument
        fields = ['id', 'year', 'pdf', 'uploaded_at']
