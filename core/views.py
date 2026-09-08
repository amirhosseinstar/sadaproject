"""
API نیروی انسانی، شعب و متقاضیان تدریس.

  GET/POST         /api/core/branches/       -> لیست شعب (خواندن برای همه، نوشتن فقط ادمین)
  GET/PUT/DELETE    /api/core/branches/<id>/  -> جزئیات یک شعبه

  GET               /api/core/employees/      -> نیروی انسانی (فقط خواندن از این مسیر؛
                                                   تنها راه ساخته شدن یک «مدرس» تأیید
                                                   درخواستش در teacher-applicants است)
  GET/PUT/DELETE     /api/core/employees/<id>/

  POST                       /api/core/teacher-applicants/          -> ثبت درخواست همکاری (برای همه، حتی بدون ورود)
  GET/DELETE                 /api/core/teacher-applicants/<id>/     -> مشاهده/حذف یک درخواست (پنل ادمین)
  POST                       /api/core/teacher-applicants/<id>/approve/  -> تأیید درخواست؛ همین‌جا یک Employee واقعی ساخته می‌شود
"""

from django.contrib.auth import get_user_model
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Branch, Employee, TeacherApplicant
from .serializers import BranchSerializer, EmployeeSerializer, StaffSerializer, TeacherApplicantSerializer
from .services import ApprovalError, approve_teacher_applicant

User = get_user_model()


class IsStaffOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsStaffOrReadOnly]


class EmployeeViewSet(viewsets.ModelViewSet):
    """
    عمداً فقط GET/PUT/DELETE کاربردی است (create از طریق این مسیر معنی
    ندارد): تنها راه ساخته شدن یک نیروی «مدرس» تازه، تأیید درخواستش در
    TeacherApplicantViewSet.approve است - همان‌جایی که هم‌زمان حساب ورودش
    هم ساخته می‌شود. این محدودیت را http_method_names تضمین می‌کند.

    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل TeacherApplicantViewSet،
    الان GET/PUT/DELETE برای راحتی توسعه باز است (چون پنل ادمین HTML هنوز
    خودش وارد نمی‌شود/نشست ندارد). وقتی احراز هویت پنل ادمین ساخته شد،
    حتماً این را به IsAdminUser محدود کنید.
    """
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)
        return qs


class StaffViewSet(viewsets.ModelViewSet):
    """
    متصدیان (مدیر آموزش/مسئول آموزش) - بر خلاف EmployeeViewSet (که فقط
    خواندنی است چون مدرس فقط از تأیید درخواست ساخته می‌شود)، اینجا
    افزودن/ویرایش/حذف مستقیم مجاز است؛ این تنها راه ساخته‌شدن یک متصدی
    است - از پنل ادمین جنگو دیگر نمی‌شود متصدی ساخت.

    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): فعلاً برای راحتی توسعه باز
    است؛ وقتی احراز هویت واقعی آماده شد، این را به «فقط مدیر آموزش»
    محدود کنید (چون همین الان هرکسی نظری به این آدرس بزند می‌تواند
    متصدی جدید بسازد).
    """
    queryset = Employee.objects.filter(role__in=['مدیر آموزش', 'مسئول آموزش'])
    serializer_class = StaffSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = Employee.objects.filter(role__in=['مدیر آموزش', 'مسئول آموزش'])
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def perform_create(self, serializer):
        username = (serializer.validated_data.pop('username', '') or '').strip()
        password = serializer.validated_data.pop('password', '') or ''
        if not username or not password:
            raise serializers.ValidationError({'detail': 'نام‌کاربری و رمز عبور برای متصدی جدید الزامی است.'})
        if User.objects.filter(username=username).exists():
            raise serializers.ValidationError({'detail': f'نام کاربری «{username}» قبلاً استفاده شده است.'})
        user = User.objects.create_user(username=username, password=password)
        serializer.save(user=user)

    def perform_update(self, serializer):
        username = (serializer.validated_data.pop('username', '') or '').strip()
        password = serializer.validated_data.pop('password', '') or ''
        instance = serializer.instance

        if instance.user:
            if username and username != instance.user.username:
                if User.objects.filter(username=username).exclude(pk=instance.user.pk).exists():
                    raise serializers.ValidationError({'detail': f'نام کاربری «{username}» قبلاً استفاده شده است.'})
                instance.user.username = username
            if password:
                instance.user.set_password(password)
            instance.user.save()
        elif username and password:
            if User.objects.filter(username=username).exists():
                raise serializers.ValidationError({'detail': f'نام کاربری «{username}» قبلاً استفاده شده است.'})
            user = User.objects.create_user(username=username, password=password)
            serializer.save(user=user)
            return

        serializer.save()


class TeacherApplicantViewSet(viewsets.ModelViewSet):
    """
    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): الان همه‌ی این مسیرها برای
    راحتی توسعه باز هستند (چون پنل ادمین HTML هنوز خودش وارد نمی‌شود/نشست
    ندارد). وقتی احراز هویت پنل ادمین ساخته شد، حتماً GET/DELETE/approve
    را به IsAdminUser (فقط کارکنان وارد‌شده) محدود کنید، چون این رکوردها
    اطلاعات شخصی متقاضیان (تلفن، آدرس، عکس) را دارند.
    """
    queryset = TeacherApplicant.objects.all()
    serializer_class = TeacherApplicantSerializer
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == 'list':
            # فهرست «مدرسین متقاضی» فقط درخواست‌های در انتظار بررسی را نشان
            # می‌دهد؛ درخواست‌های تأییدشده از اینجا محو می‌شوند و در فهرست
            # «مدرسین تأییدشده» (core/employees) دیده می‌شوند.
            qs = qs.filter(status=TeacherApplicant.STATUS_PENDING)
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        applicant = self.get_object()
        username = request.data.get('username')
        password = request.data.get('password')
        try:
            employee = approve_teacher_applicant(applicant, username, password)
        except ApprovalError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'applicant': self.get_serializer(applicant).data,
            'employee': EmployeeSerializer(employee, context=self.get_serializer_context()).data,
        })
