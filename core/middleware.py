"""
قفلِ «بخش‌های بسته‌شده» برای مسئول آموزش (core/sections.py را ببینید).

این میدلور فقط روی کاربرِ واردشده با سمت «مسئول آموزش» اثر دارد؛ مدیر آموزش، مدرس، دانش‌پژوه و بازدیدکننده‌ی
عمومی هرگز با آن روبه‌رو نمی‌شوند. اگر مسئول به بخشی که مدیر برایش بسته است درخواست بفرستد، پیش از رسیدن به
View با ۴۰۳ و پیام فارسی رد می‌شود.
"""

from django.http import JsonResponse

from core.permissions import ROLE_OFFICER, staff_role
from core.sections import SECTION_LABELS, denied_sections, section_for_request


class OfficerSectionAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/'):
            user = getattr(request, 'user', None)
            if staff_role(user) == ROLE_OFFICER:
                section = section_for_request(request.path, request.method)
                if section and section in denied_sections(user):
                    return JsonResponse(
                        {'detail': f'مدیر آموزش دسترسی شما به بخش «{SECTION_LABELS[section]}» را بسته است.'},
                        status=403, json_dumps_params={'ensure_ascii': False},
                    )
        return self.get_response(request)
