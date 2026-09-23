from rest_framework import serializers

from sada_project.utils import parse_jalali_date

from .models import TeacherPayment

MAX_AMOUNT = 10 ** 12        # سقف منطقی مبلغ (تومان) تا ورودی اشتباه ذخیره نشود
MAX_RATE = 10 ** 9


class PaymentInputSerializer(serializers.Serializer):
    """
    ورودی ثبت/ویرایش پرداخت. مبلغ و تاریخ و روش الزامی‌اند (در ویرایش جزئی، فقط
    فیلدهای فرستاده‌شده بررسی می‌شوند).

      - مبلغ: عدد صحیح ۱ تا ۱۰۰۰ میلیارد تومان (دستیِ نهایی؛ لازم نیست دقیقاً ساعت × نرخ باشد)
      - نوع حق‌الزحمه: ساعتی (پیش‌فرض) یا ماهیانه؛ نرخ هر ساعت / مبلغ ماهیانه اختیاری‌اند و فقط
        مقدارِ مربوط به همان نوع ذخیره می‌شود
      - تاریخ پرداخت: شمسی معتبر و نه آینده (پرداختِ انجام‌شده را ثبت می‌کنیم)؛ با رقم انگلیسی
        و قالب YYYY/MM/DD ذخیره می‌شود
    """
    amount = serializers.IntegerField(min_value=1, max_value=MAX_AMOUNT)
    fee_type = serializers.ChoiceField(choices=TeacherPayment.FEE_CHOICES, required=False)
    hourly_rate = serializers.IntegerField(min_value=0, max_value=MAX_RATE, required=False, allow_null=True)
    monthly_fee = serializers.IntegerField(min_value=0, max_value=MAX_AMOUNT, required=False, allow_null=True)
    paid_date = serializers.CharField(max_length=20)
    method = serializers.ChoiceField(choices=TeacherPayment.METHOD_CHOICES)
    tracking_code = serializers.CharField(max_length=50, required=False, allow_blank=True, trim_whitespace=True)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        # فقط مقدارِ مربوط به «نوع حق‌الزحمه» نگه داشته می‌شود (ماهیانه ← نرخ ساعتی پاک؛ ساعتی ← مبلغ ماهیانه پاک)
        fee_type = attrs.get('fee_type')
        if fee_type == TeacherPayment.FEE_MONTHLY:
            attrs['hourly_rate'] = None
        elif fee_type == TeacherPayment.FEE_HOURLY:
            attrs['monthly_fee'] = None
        return attrs

    def validate_paid_date(self, value):
        parsed = parse_jalali_date(value)
        if parsed is None:
            raise serializers.ValidationError('تاریخ پرداخت نامعتبر است (تاریخ آینده هم قبول نیست).')
        return f'{parsed[0]:04d}/{parsed[1]:02d}/{parsed[2]:02d}'


class CancelInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)
