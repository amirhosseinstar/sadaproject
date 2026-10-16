"""
گزارشات تحلیلی پنل مدیر آموزش.

GET /api/classmgmt/analytics/?branch=<نام شعبه یا خالی=ملی>&term=<شناسه‌ی دوره>

همه‌ی اعداد از داده‌ی واقعی سامانه محاسبه می‌شوند (بدون عدد نمونه):
  - ثبت‌نام‌ها، کلاس‌ها، سمینارها، آزمون و نمرات (قبول/مردود/غایب/در انتظار نمره) در دوره‌ی انتخاب‌شده
  - سری چنددوره‌ای برای نمودار خطی مقایسه با دوره‌های قبل
  - دانش‌پژوهان ثبت‌شده، مدرسین و متقاضیان
  - انتقادات و پیشنهادات (جمع و روند ماهانه‌ی شمسی)
قبولی: نمره‌ی حداقل ۷۵ و غیرغایب (همان قاعده‌ی «سوابق آموزشی»).
"""
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from academic_calendar.models import AcademicTerm
from core.models import Employee, TeacherApplicant
from core.permissions import IsEducationManager, branch_values
from feedback.branches import canonical_branch_name
from feedback.models import Feedback
from members.models import Member
from sada_project.utils import gregorian_to_jalali

from .models import Class, Enrollment, Lesson, Seminar, SeminarEnrollment

PASS_MIN_SCORE = 75
JALALI_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']


def _term_label(term):
    return f'دوره {term.order:02d} - {term.year}'


def _term_dict(term):
    return {'id': term.id, 'label': _term_label(term), 'year': term.year, 'order': term.order}


def _current_term(terms):
    """دوره‌ای که امروز (شمسی) در بازه‌ی برگزاری کلاس‌هایش است؛ وگرنه آخرین دوره‌ی شروع‌شده؛ وگرنه آخرین دوره."""
    if not terms:
        return None
    today = timezone.localdate()
    jy, jm, jd = gregorian_to_jalali(today.year, today.month, today.day)
    now_key = (jy, jm, jd)

    def key(point):
        return (point['m'], point['d'])

    started = []
    for t in terms:
        try:
            s, e = t.classes['start'], t.classes['end']
        except (TypeError, KeyError):
            continue
        if t.year == jy and key(s) <= (jm, jd) <= key(e):
            return t
        if (t.year, key(s)[0], key(s)[1]) <= now_key:
            started.append(t)
    return started[-1] if started else terms[-1]


def _enrollment_scope(branch_names, lesson_names):
    """ثبت‌نام‌های یک شعبه: با شعبه‌ی کلاس (یا شعبه‌ی درس اگر کلاس حذف شده)."""
    return Q(class_obj__branch__in=branch_names) | Q(class_obj__isnull=True, lesson__branch__in=lesson_names)


class AnalyticsView(APIView):
    permission_classes = [IsEducationManager]

    def get(self, request):
        raw_branch = (request.query_params.get('branch') or '').strip()
        national = raw_branch in ('', 'national', 'ملی')
        branch = ''
        if not national:
            branch = canonical_branch_name(raw_branch)
            if not branch:
                return Response({'detail': 'شعبه‌ی انتخاب‌شده معتبر نیست.'}, status=400)

        # ---------- دوره‌ها ----------
        terms = list(AcademicTerm.objects.order_by('year', 'order'))
        term = None
        term_param = request.query_params.get('term')
        if term_param and str(term_param).isdigit():
            term = next((t for t in terms if t.id == int(term_param)), None)
        term = term or _current_term(terms)
        idx = terms.index(term) if term in terms else -1
        prev_term = terms[idx - 1] if idx > 0 else None
        window = terms[max(idx - 7, 0): idx + 1] if idx >= 0 else []

        # ---------- دامنه‌ی شعبه ----------
        if national:
            enroll_q = Q()
            class_q = Q()
            seminar_q = Q()
            member_q = Q()
            employee_q = Q()
            applicant_q = Q()
            feedback_q = Q()
        else:
            cb = branch_values(Class, branch)
            lb = branch_values(Lesson, branch)
            enroll_q = _enrollment_scope(cb, lb)
            class_q = Q(branch__in=cb)
            seminar_q = Q(branch__in=branch_values(Seminar, branch))
            member_q = Q(branch__in=branch_values(Member, branch))
            employee_q = Q(branch__in=branch_values(Employee, branch))
            applicant_q = Q(branch__in=branch_values(TeacherApplicant, branch))
            feedback_q = Q(branch__in=branch_values(Feedback, branch))

        def enroll_stats(t):
            """شمارش‌های ثبت‌نام/کلاس یک دوره."""
            enr = Enrollment.objects.filter(enroll_q, class_obj__term=t)
            classes = Class.objects.filter(class_q, term=t)
            passed = enr.filter(absent=False, score__gte=PASS_MIN_SCORE).count()
            absent = enr.filter(absent=True).count()
            failed_low = enr.filter(absent=False, score__isnull=False, score__lt=PASS_MIN_SCORE).count()
            return {
                'enrollments': enr.count(),
                'students': enr.values('member_id').distinct().count(),
                'classes': classes.count(),
                'passed': passed,
                'failed': failed_low + absent,
                'failed_low': failed_low,
                'absent': absent,
                'pending': enr.filter(absent=False, score__isnull=True).count(),
            }

        series = []
        for t in window:
            st = enroll_stats(t)
            series.append({'term_id': t.id, 'label': _term_label(t), 'short': f'{t.order:02d}', 'year': t.year, **st})
        cur = next((s for s in series if term and s['term_id'] == term.id), None) or {}
        prv = next((s for s in series if prev_term and s['term_id'] == prev_term.id), None)
        if prev_term is not None and prv is None:
            prv = {**enroll_stats(prev_term)}

        # ---------- جزئیات دوره‌ی انتخاب‌شده ----------
        enr_qs = Enrollment.objects.filter(enroll_q, class_obj__term=term) if term else Enrollment.objects.none()
        cls_qs = Class.objects.filter(class_q, term=term) if term else Class.objects.none()
        sem_qs = Seminar.objects.filter(seminar_q, term=term) if term else Seminar.objects.none()

        capacity = cls_qs.aggregate(s=Sum('capacity'))['s'] or 0
        by_dept = list(
            enr_qs.values('class_obj__department__name').annotate(n=Count('id')).order_by('-n')[:8]
        )
        by_type = list(cls_qs.values('class_type').annotate(n=Count('id')).order_by('-n'))
        enr_by_type = list(enr_qs.values('class_obj__class_type').annotate(n=Count('id')).order_by('-n'))
        scored = enr_qs.filter(absent=False, score__isnull=False)
        exam_classes = cls_qs.filter(has_online_exam=True)
        avg_score = scored.aggregate(a=Sum('score'))['a']
        avg_score = round(avg_score / scored.count(), 1) if avg_score and scored.count() else None

        # ---------- دانش‌پژوهان، مدرسین ----------
        members_qs = Member.objects.filter(member_q)
        members_total = members_qs.count()
        enrolled_ever = Enrollment.objects.filter(enroll_q).values('member_id').distinct().count() if not national \
            else Enrollment.objects.values('member_id').distinct().count()
        teachers_qs = Employee.objects.filter(employee_q, role='مدرس')
        active_teachers = cls_qs.exclude(teacher__isnull=True).values('teacher_id').distinct().count()

        # ---------- انتقادات و پیشنهادات ----------
        fb = Feedback.objects.filter(feedback_q)
        today = timezone.localdate()
        jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
        months = []
        y, m = jy, jm
        for _i in range(6):
            months.append((y, m))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        months.reverse()
        buckets = {k: {'complaint': 0, 'suggestion': 0} for k in months}
        since = timezone.now() - timedelta(days=200)
        for created, kind in fb.filter(created_at__gte=since).values_list('created_at', 'kind'):
            d = timezone.localtime(created).date()
            jyy, jmm, _jd = gregorian_to_jalali(d.year, d.month, d.day)
            if (jyy, jmm) in buckets and kind in buckets[(jyy, jmm)]:
                buckets[(jyy, jmm)][kind] += 1
        monthly = [{'label': JALALI_MONTHS[mm - 1], 'complaint': buckets[(yy, mm)]['complaint'],
                    'suggestion': buckets[(yy, mm)]['suggestion']} for (yy, mm) in months]
        fb_total = fb.count()
        fb_answered = fb.filter(status=Feedback.STATUS_ANSWERED).count()

        return Response({
            'scope': {'national': national, 'branch': branch, 'label': 'ملی (همه‌ی شعب)' if national else f'شعبه‌ی {branch}'},
            'terms': [_term_dict(t) for t in terms],
            'term': _term_dict(term) if term else None,
            'prev_term': _term_dict(prev_term) if prev_term else None,
            'current': cur,
            'previous': prv,
            'series': series,
            'details': {
                'capacity': capacity,
                'fill_rate': round(cur.get('enrollments', 0) * 100 / capacity) if capacity else None,
                'exam_classes': exam_classes.count(),
                'scored': scored.count(),
                'avg_score': avg_score,
                'seminars': sem_qs.count(),
                'seminar_enrollments': SeminarEnrollment.objects.filter(seminar__in=sem_qs).count(),
                'by_department': [{'name': r['class_obj__department__name'] or '—', 'count': r['n']} for r in by_dept],
                'classes_by_type': [{'type': r['class_type'], 'count': r['n']} for r in by_type],
                'enrollments_by_type': [{'type': r['class_obj__class_type'] or '—', 'count': r['n']} for r in enr_by_type],
            },
            'people': {
                'members_total': members_total,
                'members_banned': members_qs.filter(ban__isnull=False).count(),
                'members_enrolled_ever': enrolled_ever,
                'teachers_total': teachers_qs.count(),
                'teachers_active': active_teachers,
                'applicants': TeacherApplicant.objects.filter(applicant_q).count(),
            },
            'feedback': {
                'total': fb_total,
                'complaints': fb.filter(kind=Feedback.KIND_COMPLAINT).count(),
                'suggestions': fb.filter(kind=Feedback.KIND_SUGGESTION).count(),
                'answered': fb_answered,
                'pending': fb_total - fb_answered,
                'answer_rate': round(fb_answered * 100 / fb_total) if fb_total else None,
                'monthly': monthly,
            },
        })
