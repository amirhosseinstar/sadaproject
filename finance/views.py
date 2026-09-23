# ===== مسیر این فایل در پروژه: finance/views.py (کنار manage.py) =====
"""
API پرداخت به مدرسین (فقط مدیر آموزش و مسئول آموزش؛ مسئول فقط شعبه‌ی خودش).

  GET    /api/finance/teacher-payments/classes/?branch=<شعبه>[&term=<id>]
            فهرست کلاس‌های دارای مدرسِ آن شعبه، هرکدام با وضعیت پرداخت (+ classes_without_teacher:
            کلاس‌های همان شعبه که مدرس ندارند و در فهرست نیستند)
  POST   /api/finance/teacher-payments/                  ثبت پرداخت یک کلاس
  PATCH  /api/finance/teacher-payments/<id>/             ویرایش پرداخت (فقط پرداخت فعال)
  POST   /api/finance/teacher-payments/<id>/cancel/      لغو پرداخت (سابقه می‌ماند)
  GET    /api/finance/teacher-payments/history/?class=<id>   سابقه‌ی همه‌ی پرداخت‌های یک کلاس
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from class_management.models import Class
from core.permissions import ROLE_OFFICER, IsEducationStaff, staff_role
from feedback.branches import canonical_branch_name
from logs.recorder import record

from .models import TeacherPayment, TeacherPaymentLog
from .serializers import CancelInputSerializer, PaymentInputSerializer


def _branch_key(name):
    """نام شعبه برای مقایسه: نام استانداردِ جدول شعب، وگرنه خودِ متن."""
    return canonical_branch_name(name) or (name or '').strip()


def _actor_name(user):
    employee = getattr(user, 'employee', None)
    return (employee.name if employee is not None else user.get_username()) or ''


def _deny_other_branch(request, branch):
    """
    مسئول آموزش فقط به شعبه‌ی خودش دسترسی دارد؛ اگر شعبه‌ی موردنظر فرق داشته باشد (یا
    شعبه‌ی خودش ثبت نشده باشد) پاسخ ۴۰۳ برمی‌گرداند، وگرنه None. مدیر محدودیتی ندارد.
    """
    if staff_role(request.user) != ROLE_OFFICER:
        return None
    own = _branch_key(request.user.employee.branch)
    if not own or _branch_key(branch) != own:
        return Response({'detail': 'شما فقط به امور مالی شعبه‌ی خودتان دسترسی دارید.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _money(n):
    """مبلغ با جداکننده‌ی هزارگان و رقم فارسی برای متن لاگ."""
    # (to_persian_digits فقط رقم می‌پذیرد؛ برای متنِ دارای ویرگول/جداکننده از translate استفاده می‌کنیم)
    return f'{int(n):,}'.replace(',', '٬').translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def _hours_of(cls):
    """ساعت کل دوره‌ی کلاس (خودکار از زمان‌بندی)؛ None اگر زمان‌بندی کامل نباشد."""
    raw = cls.duration_hours_raw
    return None if raw is None else Decimal(str(round(raw, 2)))


def _payment_dict(p):
    return {
        'id': p.id,
        'status': p.status,
        'status_display': p.get_status_display(),
        'class_name': p.class_name,
        'teacher_name': p.teacher_name,
        'branch': p.branch,
        'term_label': p.term_label,
        'hours': float(p.hours) if p.hours is not None else None,
        'fee_type': p.fee_type,
        'fee_type_display': p.get_fee_type_display(),
        'hourly_rate': p.hourly_rate,
        'monthly_fee': p.monthly_fee,
        'amount': p.amount,
        'paid_date': p.paid_date,
        'method': p.method,
        'method_display': p.get_method_display(),
        'tracking_code': p.tracking_code,
        'note': p.note,
        'created_by_name': p.created_by_name,
        'created_at': p.created_at,
        'canceled_at': p.canceled_at,
        'canceled_by_name': p.canceled_by_name,
        'cancel_reason': p.cancel_reason,
    }


# فیلدهای قابل ویرایش و برچسب فارسی‌شان برای سابقه‌ی تغییرات
_FIELD_LABELS = {
    'fee_type': 'نوع حق‌الزحمه',
    'hourly_rate': 'نرخ هر ساعت',
    'monthly_fee': 'حق‌الزحمه‌ی ماهیانه',
    'amount': 'مبلغ',
    'paid_date': 'تاریخ پرداخت',
    'method': 'روش پرداخت',
    'tracking_code': 'شماره پیگیری',
    'note': 'توضیحات',
}


def _display(payment, field, value):
    if field == 'method':
        return dict(TeacherPayment.METHOD_CHOICES).get(value, value)
    if field == 'fee_type':
        return dict(TeacherPayment.FEE_CHOICES).get(value, value)
    return '' if value is None else str(value)


class TeacherPaymentClassesView(APIView):
    permission_classes = [IsEducationStaff]

    def get(self, request):
        branch = request.query_params.get('branch') or ''
        if staff_role(request.user) == ROLE_OFFICER and not branch:
            branch = request.user.employee.branch     # مسئول: پیش‌فرض شعبه‌ی خودش
        if not branch.strip():
            return Response({'detail': 'شعبه مشخص نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        denied = _deny_other_branch(request, branch)
        if denied:
            return denied

        term = request.query_params.get('term')
        wanted = _branch_key(branch)
        in_branch = [
            c for c in Class.objects.select_related('teacher', 'term', 'lesson')
            if _branch_key(c.branch) == wanted and (not term or str(c.term_id) == term)
        ]
        classes = [c for c in in_branch if c.teacher_id]
        # کلاس‌های همین شعبه که «مدرس ندارند» در فهرست پرداخت نمی‌آیند (پرداخت به مدرسِ کلاس است)؛
        # اما تعدادشان را می‌فرستیم تا صفحه بتواند بگوید چرا فهرست خالی است یا کلاسی کم است
        without_teacher = [
            {'class_id': c.id, 'class_name': c.name}
            for c in sorted(in_branch, key=lambda c: (c.name, c.id)) if not c.teacher_id
        ]
        ids = [c.id for c in classes]
        paid = {p.class_obj_id: p for p in TeacherPayment.objects.filter(class_obj_id__in=ids, status='paid')}
        history_ids = set(TeacherPayment.objects.filter(class_obj_id__in=ids).values_list('class_obj_id', flat=True))

        rows = []
        for c in classes:
            hours = _hours_of(c)
            rows.append({
                'class_id': c.id,
                'class_name': c.name,
                'lesson_name': c.lesson.name if c.lesson else '',
                'teacher_id': c.teacher_id,
                'teacher_name': c.teacher.name,
                'term_id': c.term_id,
                'term_label': str(c.term) if c.term else '',
                'day': c.day,
                'start_time': c.start_time,
                'entry_time': c.entry_time,
                'hours': float(hours) if hours is not None else None,
                'payment': _payment_dict(paid[c.id]) if c.id in paid else None,
                'has_history': c.id in history_ids,
            })
        rows.sort(key=lambda r: (r['teacher_name'], r['class_name'], r['class_id']))
        return Response({'branch': wanted, 'rows': rows, 'classes_without_teacher': without_teacher})


class TeacherPaymentCreateView(APIView):
    permission_classes = [IsEducationStaff]

    def post(self, request):
        try:
            cls = Class.objects.select_related('teacher', 'term').filter(pk=int(request.data.get('class_id'))).first()
        except (TypeError, ValueError):
            cls = None
        if cls is None or cls.teacher is None:
            return Response({'detail': 'کلاس (دارای مدرس) پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        denied = _deny_other_branch(request, cls.branch)
        if denied:
            return denied

        serializer = PaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                if TeacherPayment.objects.filter(class_obj=cls, status='paid').exists():
                    return Response({'detail': 'برای این کلاس قبلاً پرداخت ثبت شده است؛ برای تغییر، آن را ویرایش یا لغو کنید.'},
                                    status=status.HTTP_400_BAD_REQUEST)
                actor = _actor_name(request.user)
                # فقط مقدارِ مربوط به نوع حق‌الزحمه ذخیره می‌شود (پیش‌فرض: ساعتی)
                fee_type = data.get('fee_type', TeacherPayment.FEE_HOURLY)
                payment = TeacherPayment.objects.create(
                    class_obj=cls, teacher=cls.teacher,
                    class_name=cls.name, teacher_name=cls.teacher.name,
                    branch=_branch_key(cls.branch), term_label=str(cls.term) if cls.term else '',
                    hours=_hours_of(cls), fee_type=fee_type,
                    hourly_rate=data.get('hourly_rate') if fee_type == TeacherPayment.FEE_HOURLY else None,
                    monthly_fee=data.get('monthly_fee') if fee_type == TeacherPayment.FEE_MONTHLY else None,
                    amount=data['amount'],
                    paid_date=data['paid_date'], method=data['method'],
                    tracking_code=data.get('tracking_code', ''), note=data.get('note', ''),
                    created_by=request.user, created_by_name=actor,
                )
                TeacherPaymentLog.objects.create(
                    payment=payment, action=TeacherPaymentLog.ACTION_CREATED, actor_name=actor,
                    changes=[{'field': 'مبلغ', 'old': '', 'new': str(payment.amount)},
                             {'field': 'تاریخ پرداخت', 'old': '', 'new': payment.paid_date}],
                )
        except IntegrityError:
            return Response({'detail': 'برای این کلاس هم‌زمان پرداخت دیگری ثبت شد.'}, status=status.HTTP_400_BAD_REQUEST)
        record(request, 'finance', 'payment_create',
               f'ثبت پرداخت {_money(payment.amount)} تومان ({payment.get_fee_type_display()}) به «{payment.teacher_name}»',
               target_type='پرداخت به مدرس', target_id=str(payment.pk), target_label=f'{payment.teacher_name} — {payment.class_name}',
               branch=payment.branch)
        return Response(_payment_dict(payment), status=status.HTTP_201_CREATED)


class TeacherPaymentDetailView(APIView):
    permission_classes = [IsEducationStaff]

    def _get(self, request, pk):
        payment = TeacherPayment.objects.filter(pk=pk).first()
        if payment is None:
            return None, Response({'detail': 'پرداخت پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        denied = _deny_other_branch(request, payment.branch)
        if denied:
            return None, denied
        return payment, None

    def patch(self, request, pk):
        payment, error = self._get(request, pk)
        if error:
            return error
        if payment.status != TeacherPayment.STATUS_PAID:
            return Response({'detail': 'پرداخت لغوشده قابل ویرایش نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = PaymentInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        changes = []
        for field, new in serializer.validated_data.items():
            old = getattr(payment, field)
            if old == new:
                continue      # این فیلد عوض نشده؛ در سابقه نمی‌آید
            changes.append({'field': _FIELD_LABELS[field], 'old': _display(payment, field, old), 'new': _display(payment, field, new)})
            setattr(payment, field, new)
        # اگر نوع حق‌الزحمه عوض شده، مقدارِ نوعِ قبلی نباید بماند (ماهیانه ← نرخ ساعتی پاک و برعکس)
        stale = 'hourly_rate' if payment.fee_type == TeacherPayment.FEE_MONTHLY else 'monthly_fee'
        if getattr(payment, stale) is not None:
            changes.append({'field': _FIELD_LABELS[stale], 'old': _display(payment, stale, getattr(payment, stale)), 'new': ''})
            setattr(payment, stale, None)
        if not changes:
            return Response({'detail': 'تغییری برای ذخیره وجود ندارد.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            payment.save()
            TeacherPaymentLog.objects.create(
                payment=payment, action=TeacherPaymentLog.ACTION_EDITED, actor_name=_actor_name(request.user), changes=changes,
            )
        record(request, 'finance', 'payment_update', f'ویرایش پرداخت «{payment.teacher_name}» — {payment.class_name}',
               target_type='پرداخت به مدرس', target_id=str(payment.pk), target_label=f'{payment.teacher_name} — {payment.class_name}',
               branch=payment.branch, changes=changes)
        return Response(_payment_dict(payment))


class TeacherPaymentCancelView(TeacherPaymentDetailView):
    def post(self, request, pk):
        payment, error = self._get(request, pk)
        if error:
            return error
        if payment.status != TeacherPayment.STATUS_PAID:
            return Response({'detail': 'این پرداخت قبلاً لغو شده است.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = CancelInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = _actor_name(request.user)
        reason = serializer.validated_data.get('reason', '')
        with transaction.atomic():
            payment.status = TeacherPayment.STATUS_CANCELED
            payment.canceled_at = timezone.now()
            payment.canceled_by_name = actor
            payment.cancel_reason = reason
            payment.save()
            TeacherPaymentLog.objects.create(
                payment=payment, action=TeacherPaymentLog.ACTION_CANCELED, actor_name=actor,
                changes=[{'field': 'دلیل لغو', 'old': '', 'new': reason}] if reason else [],
            )
        record(request, 'finance', 'payment_cancel',
               f'لغو پرداخت {_money(payment.amount)} تومان به «{payment.teacher_name}» — {payment.class_name}',
               target_type='پرداخت به مدرس', target_id=str(payment.pk), target_label=f'{payment.teacher_name} — {payment.class_name}',
               branch=payment.branch, changes=[{'field': 'دلیل لغو', 'old': '', 'new': reason}] if reason else [])
        return Response(_payment_dict(payment))


class TeacherPaymentHistoryView(APIView):
    permission_classes = [IsEducationStaff]

    def get(self, request):
        try:
            cls = Class.objects.filter(pk=int(request.query_params.get('class'))).first()
        except (TypeError, ValueError):
            cls = None
        if cls is None:
            return Response({'detail': 'کلاس پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        denied = _deny_other_branch(request, cls.branch)
        if denied:
            return denied
        payments = TeacherPayment.objects.filter(class_obj=cls).prefetch_related('logs')
        result = []
        for p in payments:
            d = _payment_dict(p)
            d['logs'] = [
                {'action': l.action, 'action_display': l.get_action_display(), 'actor_name': l.actor_name, 'at': l.at, 'changes': l.changes}
                for l in p.logs.all()
            ]
            result.append(d)
        return Response({'class_id': cls.id, 'class_name': cls.name, 'payments': result})
