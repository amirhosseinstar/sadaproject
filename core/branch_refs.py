"""
هماهنگ‌سازیِ «نام شعبه» بین مدل‌ها.

در این پروژه شعبه در مدل‌های مختلف (نیروی انسانی، کلاس، عضو، درخواست مدرس، انتقادات و ...)
به‌صورت «متن» ذخیره می‌شود، نه کلید خارجی. پس وقتی نام یک شعبه عوض می‌شود یا شعبه حذف
می‌شود، باید این متن‌ها هم‌زمان به‌روز شوند؛ وگرنه مسئولِ آن شعبه (که دسترسی‌اش بر اساس
همین متن سنجیده می‌شود) بی‌دسترسی می‌شود یا رکوردها «یتیم» می‌مانند.

همه‌ی مقایسه‌ها با نامِ یکدست‌شده (ی/ک عربی، نیم‌فاصله، فاصله‌ی اضافه) انجام می‌شود.
"""

from django.apps import apps
from django.db import models

from core.permissions import ROLE_MANAGER, ROLE_OFFICER, ROLE_TEACHER, same_branch

# مدل‌هایی که عمداً دست‌نخورده می‌مانند:
#  - logs.AuditLog: لاگ «فقط‌اضافه‌شونده» است و هیچ‌وقت نباید ویرایش شود (نام شعبه در لاگ‌های قدیمی همان می‌ماند).
#  - finance.TeacherPayment: بخش امور مالی قرار است کاملاً بازطراحی شود؛ فعلاً کنار گذاشته شده است.
SKIPPED_MODELS = {'logs.auditlog', 'finance.teacherpayment'}


def branch_reference_fields():
    """(مدل، نام فیلد) همه‌ی مدل‌هایی که یک فیلد متنیِ «branch» دارند (به‌جز SKIPPED_MODELS)."""
    for model in apps.get_models():
        if model._meta.label_lower in SKIPPED_MODELS:
            continue
        for field in model._meta.get_fields():
            if isinstance(field, models.CharField) and field.name == 'branch' and field.concrete:
                yield model, field.name


def _matching_values(model, field, branch_name):
    """مقادیرِ متمایزِ این فیلد که (با اختلاف‌های نگارشی) همان شعبه‌اند."""
    values = model._default_manager.order_by().values_list(field, flat=True).distinct()
    return [v for v in values if same_branch(v, branch_name)]


def rename_branch_references(old_name, new_name):
    """
    نام شعبه را در همه‌ی رکوردهای مرتبط از old_name به new_name تغییر می‌دهد.
    خروجی: {نام مدل: تعداد رکوردِ به‌روزشده}. باید داخل transaction.atomic صدا زده شود.
    """
    counts = {}
    for model, field in branch_reference_fields():
        values = _matching_values(model, field, old_name)
        if not values:
            continue
        updated = model._default_manager.filter(**{f'{field}__in': values}).update(**{field: new_name})
        if updated:
            counts[str(model._meta.verbose_name or model._meta.label)] = updated
    return counts


def employees_of_branch(branch_name):
    """نیروهای انسانی (مدیر/مسئول/مدرس) این شعبه."""
    from core.models import Employee
    return [e for e in Employee.objects.select_related('user') if same_branch(e.branch, branch_name)]


def _count(model, branch_name, field='branch'):
    return sum(
        model._default_manager.filter(**{field: v}).count()
        for v in _matching_values(model, field, branch_name)
    )


def branch_impact(branch_name):
    """
    پیامدهای حذف یک شعبه (برای نمایش در پیام تأیید پنل). با حذف شعبه، مسئولان/مدرسین، کلاس‌ها، سمینارها، درس‌ها،
    دپارتمان‌های شعبه، درخواست‌های همکاری و انتقادات حذف می‌شوند. «members» فقط برای اطلاع است: اعضا حذف
    نمی‌شوند. اگر managers > ۰ باشد (شعبه «مدیر آموزش» دارد) حذف شعبه رد می‌شود.
    """
    from class_management.models import BranchDepartment, Class, Lesson, Seminar
    from core.models import TeacherApplicant
    from feedback.models import Feedback
    from members.models import Member

    people = employees_of_branch(branch_name)
    return {
        'managers': sum(1 for e in people if e.role == ROLE_MANAGER),
        'officers': sum(1 for e in people if e.role == ROLE_OFFICER),
        'teachers': sum(1 for e in people if e.role == ROLE_TEACHER),
        'classes': _count(Class, branch_name),
        'seminars': _count(Seminar, branch_name),
        'lessons': _count(Lesson, branch_name),
        'departments': _count(BranchDepartment, branch_name),
        'members': _count(Member, branch_name),
        'applicants': _count(TeacherApplicant, branch_name),
        'feedback': _count(Feedback, branch_name),
    }


def _delete_matching(model, branch_name, field='branch'):
    """همه‌ی رکوردهای این مدل که شعبه‌شان همین شعبه است حذف می‌شود؛ تعداد حذف‌شده برمی‌گردد."""
    values = _matching_values(model, field, branch_name)
    if not values:
        return 0
    queryset = model._default_manager.filter(**{f'{field}__in': values})
    count = queryset.count()
    queryset.delete()
    return count


def delete_branch_data(branch_name):
    """
    اطلاعات «خودِ شعبه» را برای همیشه حذف می‌کند (به‌جز نیروهای انسانی که جداگانه و با ثبتِ لاگِ تک‌تکشان
    حذف می‌شوند): کلاس‌ها، سمینارها، درس‌ها (و سؤال‌ها/مجوزهای درس)، دپارتمان‌های فعال‌شده‌ی شعبه،
    درخواست‌های همکاری مدرس و انتقادات/پیشنهادات.

    عمداً حذف «نمی‌شوند»:
      - اعضا (دانش‌پژوهان): حساب ورود، ثبت‌نام‌ها، نمره‌ها، محرومیت‌ها و پاسخ‌های نظرسنجی‌شان می‌ماند.
        (با حذف یک کلاس، ثبت‌نامِ دانش‌پژوه می‌ماند و فقط ارتباطش با کلاسِ حذف‌شده خالی می‌شود؛ سابقه‌ی
        درس و نمره‌ی او از بین نمی‌رود.)
      - لاگ (فقط‌اضافه‌شونده است) و ردیف‌های امور مالی (فعلاً کنار گذاشته شده).

    خروجی: {عنوان فارسی: تعداد}. باید داخل transaction.atomic صدا زده شود.
    """
    from class_management.models import BranchDepartment, Class, Lesson, Seminar
    from core.models import TeacherApplicant
    from feedback.models import Feedback

    counts = {}

    def add(title, number):
        if number:
            counts[title] = counts.get(title, 0) + number

    add('کلاس', _delete_matching(Class, branch_name))
    add('سمینار', _delete_matching(Seminar, branch_name))
    add('درس', _delete_matching(Lesson, branch_name))
    add('دپارتمان شعبه', _delete_matching(BranchDepartment, branch_name))
    add('درخواست همکاری مدرس', _delete_matching(TeacherApplicant, branch_name))
    add('انتقاد/پیشنهاد', _delete_matching(Feedback, branch_name))

    # جدول‌های قدیمی (مثل members.Teacher) که فیلد شعبه دارند و هنوز چیزی در آن‌ها مانده.
    # اعضا و پاسخ‌های نظرسنجی «handled» حساب می‌شوند تا این جاروی عمومی به آن‌ها دست نزند.
    handled = {
        'class_management.class', 'class_management.seminar', 'class_management.lesson',
        'class_management.branchdepartment', 'members.member', 'core.teacherapplicant', 'feedback.feedback',
        'feedback.classsurveyresponse', 'core.employee',
    }
    for model, field in branch_reference_fields():
        if model._meta.label_lower not in handled:
            add(str(model._meta.verbose_name), _delete_matching(model, branch_name, field))
    return counts
