"""
API تقویم آموزشی.

  GET  /api/calendar/              -> تقویم یک سال، به همان شکلی که سایت اصلی
                                       (سدا.html) نمایش می‌دهد. با ?year=1405
                                       می‌شود سال دلخواه را خواست.
  GET  /api/calendar/years/        -> لیست سال‌هایی که در تقویم ثبت شده‌اند

  GET    /api/calendar/terms/      -> لیست خام دوره‌ها (برای پنل ادمین)
  POST   /api/calendar/terms/      -> ساخت دوره‌ی جدید (فقط ادمین/مدیر آموزش)
  GET    /api/calendar/terms/<id>/ -> جزئیات یک دوره
  PUT    /api/calendar/terms/<id>/ -> ویرایش یک دوره (فقط ادمین/مدیر آموزش)
  DELETE /api/calendar/terms/<id>/ -> حذف یک دوره (فقط ادمین/مدیر آموزش)

  GET  /api/calendar/pdf/?year=Y   -> اطلاعات فایل PDF تقویم آن سال (404 اگر آپلود نشده)
  POST /api/calendar/pdf/          -> آپلود/جایگزینی فایل PDF (فرم: year, pdf)
"""

from rest_framework import permissions, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AcademicTerm, CalendarDocument
from .serializers import AcademicTermSerializer, CalendarDocumentSerializer, TermAsPeriodSerializer


class PublicCalendarView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        year_param = request.query_params.get('year')

        if year_param:
            year = int(year_param)
        else:
            latest = AcademicTerm.objects.filter(is_active=True).order_by('-year').first()
            if latest is None:
                return Response({'year': None, 'periods': []})
            year = latest.year

        terms = AcademicTerm.objects.filter(year=year, is_active=True).order_by('order')
        periods = TermAsPeriodSerializer(terms, many=True).data
        return Response({'year': year, 'periods': periods})


class CalendarYearsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        years = list(
            AcademicTerm.objects.order_by('-year').values_list('year', flat=True).distinct()
        )
        return Response({'years': years})


class AcademicTermViewSet(viewsets.ModelViewSet):
    """
    CRUD کامل روی دوره‌های تقویم آموزشی - همان چیزی که دکمه‌ی
    «ویرایش تقویم» در پنل ادمین استفاده می‌کند.

    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل بقیه‌ی ViewSetهای این
    پروژه، الان نوشتن (POST/PUT/DELETE) برای راحتی توسعه باز است (چون پنل
    ادمین HTML هنوز خودش وارد نمی‌شود/نشست ندارد). وقتی احراز هویت پنل
    ادمین ساخته شد، حتماً این را به IsAdminUser محدود کنید.
    """
    queryset = AcademicTerm.objects.all().order_by('year', 'order')
    serializer_class = AcademicTermSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(year=year)
        return qs


class CalendarPdfView(APIView):
    """
    فایل PDF رسمی تقویم آموزشی یک سال - جدا از داده‌ی ساختاریافته‌ی
    AcademicTerm. دکمه‌ی «آپلود PDF تقویم» در پنل ادمین این را POST می‌کند؛
    سایت اصلی (سدا.html) با GET همین مسیر لینک دانلود را نشان می‌دهد.

    TODO (فاز آینده - ورود مسئولین/ادمین‌ها): مثل AcademicTermViewSet، فعلاً
    POST هم برای همه باز است؛ وقتی احراز هویت پنل ادمین ساخته شد محدودش کنید.
    """
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        year = request.query_params.get('year')
        if not year:
            return Response({'detail': 'پارامتر year لازم است.'}, status=400)
        doc = CalendarDocument.objects.filter(year=year).first()
        if doc is None:
            return Response({'detail': 'برای این سال فایل PDF آپلود نشده است.'}, status=404)
        return Response(CalendarDocumentSerializer(doc, context={'request': request}).data)

    def post(self, request):
        year = request.data.get('year')
        pdf = request.FILES.get('pdf')
        if not year:
            return Response({'detail': 'سال را مشخص کنید.'}, status=400)
        if not pdf:
            return Response({'detail': 'فایل PDF را انتخاب کنید.'}, status=400)
        if not pdf.name.lower().endswith('.pdf'):
            return Response({'detail': 'فقط فایل با فرمت PDF مجاز است.'}, status=400)

        doc, _ = CalendarDocument.objects.update_or_create(year=year, defaults={'pdf': pdf})
        return Response(CalendarDocumentSerializer(doc, context={'request': request}).data, status=201)
