"""
API دپارتمان‌ها، کلاس‌ها و ثبت‌نام.

  GET/POST/DELETE  /api/classmgmt/departments/            -> دپارتمان‌ها
  GET/POST/DELETE  /api/classmgmt/branch-departments/      -> کدام دپارتمان در کدام شعبه فعال است
                     (?branch=... برای فیلتر)

  GET/POST/PUT/DELETE /api/classmgmt/classes/              -> کلاس‌ها
                     (?department=..&branch=..&gender=..&published=..&term=.. برای فیلتر)
  POST /api/classmgmt/classes/<id>/enroll/                 -> ثبت‌نام یک دانش‌پژوه در این کلاس
                     بدنه: national_id, membership_code
                     همین‌جا هویت را هم تأیید می‌کند (عضو هست؟ محروم نیست؟
                     عضویتش معتبر است؟ ظرفیت خالی هست؟) - نقطه‌ی واحد ثبت‌نام.

  GET /api/classmgmt/classes/<id>/students/                -> لیست دانش‌پژوهان ثبت‌نامی این کلاس

TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل بقیه‌ی این پروژه، فعلاً نوشتن
برای همه باز است چون پنل ادمین HTML هنوز خودش وارد نمی‌شود.
"""

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from members.models import Member

from .models import BranchDepartment, Class, Department, Enrollment, Lesson, SiteSettings
from .serializers import (
    BranchDepartmentSerializer,
    ClassSerializer,
    DepartmentSerializer,
    EnrollmentSerializer,
    LessonSerializer,
    SiteSettingsSerializer,
)


class SiteSettingsView(APIView):
    """
    تنظیمات سراسری سایت (فعلاً فقط «دسترسی همگان به دیدن و ثبت‌نام در
    کلاس‌ها»). چون فقط یک رکورد وجود دارد، GET همیشه همان یکی را برمی‌گرداند
    و PATCH همان را به‌روز می‌کند - نیازی به id در URL نیست.

    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): طبق متن خودِ پنل ادمین، این
    فقط باید توسط «مدیر آموزش» قابل تغییر باشد؛ فعلاً مثل بقیه‌ی پروژه
    برای راحتی توسعه باز است.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(SiteSettingsSerializer(SiteSettings.load()).data)

    def patch(self, request):
        settings_obj = SiteSettings.load()
        serializer = SiteSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']


class LessonViewSet(viewsets.ModelViewSet):
    """
    درس (سرفصل) - قبل از ساخت هر کلاسی باید درسش اینجا تعریف شده باشد.
    """
    queryset = Lesson.objects.select_related('department').all()
    serializer_class = LessonSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get('department')
        if department:
            qs = qs.filter(department_id=department)
        return qs


class BranchDepartmentViewSet(viewsets.ModelViewSet):
    queryset = BranchDepartment.objects.select_related('department').all()
    serializer_class = BranchDepartmentSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch=branch)
        return qs


class ClassViewSet(viewsets.ModelViewSet):
    queryset = Class.objects.select_related('department', 'teacher').all()
    serializer_class = ClassSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        department = params.get('department')
        department_name = params.get('department_name')
        branch = params.get('branch')
        gender = params.get('gender')
        published = params.get('published')
        term = params.get('term')
        class_type = params.get('type')
        is_national = params.get('is_national')

        if department:
            qs = qs.filter(department_id=department)
        if department_name:
            qs = qs.filter(department__name__icontains=department_name)
        if class_type:
            qs = qs.filter(class_type=class_type)
        if is_national is not None:
            qs = qs.filter(is_national=is_national.lower() in ('1', 'true', 'yes'))
        if branch:
            qs = qs.filter(branch=branch)
        if gender:
            # کلاس «مختلط» برای هر دو جنسیت هم نمایش داده می‌شود
            qs = qs.filter(gender__in=[gender, 'مختلط'])
        if published is not None:
            qs = qs.filter(is_published=published.lower() in ('1', 'true', 'yes'))
        if term:
            qs = qs.filter(term_id=term)
        return qs

    @action(detail=True, methods=['get'])
    def students(self, request, pk=None):
        cls = self.get_object()
        enrollments = cls.enrollments.select_related('member', 'member__user').all()
        return Response(EnrollmentSerializer(enrollments, many=True).data)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        """
        نقطه‌ی واحد ثبت‌نام: هم هویت/محرومیت/اعتبار عضویت را چک می‌کند، هم
        ظرفیت کلاس را، هم واقعاً رکورد ثبت‌نام را می‌سازد - دقیقاً همان
        چیزی که ویزارد ثبت‌نام دوره (hozori-courses.html/majazi-courses.html)
        باید در «مرحله‌ی موفقیت» صدا بزند.
        """
        cls = self.get_object()

        # مدیر/مسئول آموزش (نیروی انسانی) حتی اگر هفته‌ی ثبت‌نام هم گذشته
        # باشد، باید بتواند از پنل خودش دستی دانش‌پژوه اضافه کند؛ این
        # محدودیت فقط برای ثبت‌نام عمومی (خودِ دانش‌پژوهان از سایت اصلی) است
        is_staff_request = request.user.is_authenticated and hasattr(request.user, 'employee')

        if not is_staff_request and not SiteSettings.load().public_registration_enabled:
            return Response(
                {'detail': 'در حال حاضر ثبت‌نام در کلاس‌ها برای عموم بسته است.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        national_id = (request.data.get('national_id') or '').strip()
        membership_code = (request.data.get('membership_code') or '').strip()
        if not national_id or not membership_code:
            return Response({'detail': 'کد ملی و کد عضویت لازم است.'}, status=status.HTTP_400_BAD_REQUEST)

        member = (
            Member.objects
            .filter(national_id=national_id, membership_code=membership_code)
            .select_related('ban')
            .first()
        )
        if member is None:
            return Response(
                {'is_member': False, 'detail': 'این کد ملی و کد عضویت در سامانه‌ی اعضا یافت نشد.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if hasattr(member, 'ban'):
            return Response(
                {'is_member': True, 'is_banned': True, 'ban_reason': member.ban.reason, 'detail': 'این عضو محروم شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not member.is_membership_valid:
            return Response(
                {'is_member': True, 'is_valid': False, 'detail': 'عضویت این فرد منقضی شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # هر دانش‌پژوه فقط می‌تواند در کلاس‌های استان خودش ثبت‌نام کند (چه
        # حضوری چه مجازی) - به‌جز کلاس‌های مجازی «سراسری» (is_national=True)
        # که برای همه‌ی استان‌ها آزاد است
        if not cls.is_national:
            from core.models import Branch
            class_branch = Branch.objects.filter(name=cls.branch).first()
            class_province = class_branch.province if class_branch else None
            if class_province and member.province and class_province != member.province:
                return Response(
                    {
                        'detail': f'این کلاس در استان «{class_province}» برگزار می‌شود؛ شما فقط می‌توانید در کلاس‌های استان «{member.province}» ثبت‌نام کنید.',
                        'wrong_province': True,
                        'class_province': class_province,
                        'member_province': member.province,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if cls.prerequisite and not Enrollment.objects.filter(lesson=cls.prerequisite, member=member).exists():
            return Response(
                {
                    'detail': 'این کلاس دارای پیش‌نیاز است.',
                    'prerequisite_required': True,
                    'prerequisite_id': cls.prerequisite.id,
                    'prerequisite_name': cls.prerequisite.name,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if cls.is_full:
            return Response({'detail': 'ظرفیت این کلاس تکمیل شده است.'}, status=status.HTTP_400_BAD_REQUEST)
        if Enrollment.objects.filter(class_obj=cls, member=member).exists():
            return Response(
                {'detail': 'قبلاً در این کلاس ثبت‌نام کرده‌اید.', 'already_enrolled': True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment = Enrollment.objects.create(class_obj=cls, lesson=cls.lesson, member=member)
        return Response(EnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)


class EnrollmentViewSet(viewsets.ModelViewSet):
    """
    فقط برای مشاهده/حذف یک ثبت‌نام (مثلاً وقتی ادمین یک دانش‌پژوه را از
    کلاس حذف می‌کند) - ساخت ثبت‌نام همیشه باید از ClassViewSet.enroll باشد
    (که هویت/محرومیت/اعتبار/ظرفیت را هم چک می‌کند)، نه مستقیم از این‌جا.

    برای «سوابق آموزشی» (پنل ادمین)، با ?member_national_id= و/یا
    ?member_membership_code= فیلتر می‌شود.
    """
    queryset = (
        Enrollment.objects
        .select_related('member', 'member__user', 'class_obj', 'class_obj__department', 'class_obj__term', 'lesson', 'lesson__department')
        .all()
    )
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        national_id = self.request.query_params.get('member_national_id')
        membership_code = self.request.query_params.get('member_membership_code')
        if national_id:
            qs = qs.filter(member__national_id=national_id)
        if membership_code:
            qs = qs.filter(member__membership_code=membership_code)
        return qs
