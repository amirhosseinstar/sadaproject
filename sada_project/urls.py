"""
نقشه‌ی آدرس‌های کل پروژه.

هیچ فایل HTML فرانت‌اند دیگر با اسم مستقیم خودش (مثلاً /sada.html یا
/hozori-courses.html) قابل باز شدن نیست - هرکدام فقط از مسیر تمیز
اختصاصی خودشان (مثل /hozori-courses) در دسترس‌اند. یک مسیر عمومی که
هر اسم فایلی را قبول کند دیگر وجود ندارد.

- /django-admin/       -> پنل مدیریت آماده‌ی خود جنگو
- /api/                -> تمام APIهایی که فرانت‌اند با آن‌ها صحبت می‌کند
- /                     -> سایت اصلی دانش‌پژوهان (sada.html)
- /admin                -> ورود مدیر آموزش/مسئول آموزش (admin-login.html)
- /login                -> ورود دانش‌پژوهان (login.html)
- /panel                -> پنل مدیر آموزش (sada-admin.html)
- /officer-panel        -> پنل مسئول آموزش (sada-admin-officer.html)
- /teacher-login        -> ورود مدرسین (teacher-login.html)
- /teacher-registration -> ثبت درخواست همکاری مدرس (teacher-registration.html)
- /department           -> صفحه‌ی دپارتمان (department.html)
- /province             -> صفحه‌ی استان (province.html)
- /hozori-courses       -> دوره‌های حضوری (hozori-courses.html)
- /majazi-courses       -> دوره‌های مجازی (majazi-courses.html)
- /majazi-courses-ostan -> دوره‌های مجازی بر اساس استان (majazi-courses-ostan.html)
"""

from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404, HttpResponse
from django.urls import include, path

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/', include('members.urls')),
    path('api/calendar/', include('academic_calendar.urls')),
    path('api/core/', include('core.urls')),
    path('api/classmgmt/', include('class_management.urls')),
]

# فایل‌های آپلودی (عکس/رزومه‌ی متقاضیان) در حالت توسعه از همین سرور جنگو
# سرو می‌شوند. در production معمولاً این کار را nginx انجام می‌دهد.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


def _serve_html_file(filename):
    """
    فقط در حالت توسعه: یک فایل HTML فرانت‌اند مشخص (که کنار manage.py است)
    را مستقیماً سرو می‌کند. filename همیشه از کد پایین همین فایل می‌آید
    (هیچ‌وقت مستقیم از URL کاربر خوانده نمی‌شود)، پس نیازی به بررسی مسیر
    امنیتی (مثل ../../) نیست.
    """
    file_path = Path(settings.BASE_DIR) / filename
    if not file_path.is_file():
        raise Http404
    return HttpResponse(file_path.read_text(encoding='utf-8'), content_type='text/html; charset=utf-8')


# نگاشت «مسیر تمیز» -> «اسم فایل واقعی». تنها جایی که این نگاشت تعریف
# می‌شود؛ اگر صفحه‌ی جدیدی اضافه شد، فقط کافی‌ست یک خط اینجا اضافه شود.
FRONTEND_ROUTES = {
    '': 'sada.html',
    'admin': 'admin-login.html',
    'login': 'login.html',
    'panel': 'sada-admin.html',
    'officer-panel': 'sada-admin-officer.html',
    'teacher-login': 'teacher-login.html',
    'teacher-registration': 'teacher-registration.html',
    'department': 'department.html',
    'province': 'province.html',
    'hozori-courses': 'hozori-courses.html',
    'majazi-courses': 'majazi-courses.html',
    'majazi-courses-ostan': 'majazi-courses-ostan.html',
}


def _make_frontend_view(filename):
    def view(request):
        return _serve_html_file(filename)
    return view


if settings.DEBUG:
    for route, filename in FRONTEND_ROUTES.items():
        view_func = _make_frontend_view(filename)
        if route == '':
            urlpatterns.append(path('', view_func, name='frontend-index'))
        else:
            # هم با اسلش آخر هم بدون آن کار کند (کاربر هرجور تایپ کند جواب بگیرد)
            urlpatterns.append(path(route, view_func, name=f'{route}-noslash'))
            urlpatterns.append(path(f'{route}/', view_func, name=f'{route}-slash'))
