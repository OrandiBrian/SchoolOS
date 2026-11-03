"""School-scoped attendance views and transactional register writes."""
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError, OperationalError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (AcademicYear, AnnualEnrollment, AttendanceChange, AttendanceEntry,
                     AttendanceRegister, LearningGroup, SchoolMembership)
from .permissions import school_access, active_membership


class StaleRegister(Exception):
    pass


def scoped_groups(membership):
    groups = LearningGroup.objects.filter(academic_year__school=membership.school).select_related('grade', 'academic_year')
    if membership.role == 'teacher':
        groups = groups.filter(teacher_assignments__membership=membership)
    return groups


def eligible_learners(group, day):
    enrollments = AnnualEnrollment.objects.filter(
        learning_group=group, learner__school=group.academic_year.school,
        enrolled_on__lte=day,
    ).filter(Q(withdrawn_on__isnull=True) | Q(withdrawn_on__gt=day)).exclude(status='withdrawn', withdrawn_on__isnull=True)
    return [item.learner for item in enrollments.select_related('learner').order_by('learner__last_name', 'learner__first_name')]


def roster(group, day, register):
    if register:
        return [{'learner': entry.learner, 'status': entry.status} for entry in register.entries.select_related('learner')]
    return [{'learner': learner, 'status': ''} for learner in eligible_learners(group, day)]


def parse_day(value):
    try:
        return date.fromisoformat(value) if value else timezone.localdate()
    except (ValueError, TypeError):
        raise ValidationError('Choose a valid date.')


def validate_day(group, day):
    if day > timezone.localdate():
        raise ValidationError('Attendance cannot be recorded for a future date.')
    if not group.academic_year.starts_on <= day <= group.academic_year.ends_on:
        raise ValidationError('Choose a date within this class’s academic year.')


@transaction.atomic
def save_register(membership, group, day, version, marks, action, reason):
    # Refresh authorization inside the write boundary; never accept posted school IDs.
    membership = active_membership(membership.user, membership.school_id)
    if not membership or membership.role not in {'head', 'teacher'}:
        raise PermissionDenied
    group = get_object_or_404(scoped_groups(membership).select_for_update(of=('self',)), pk=group.pk)
    validate_day(group, day)
    if action not in {'draft', 'submit', 'correct'}:
        raise ValidationError('Choose a valid register action.')
    register = AttendanceRegister.objects.filter(learning_group=group, date=day).first()
    if version != (register.version if register else 0):
        raise StaleRegister('Someone saved this register after you opened it. Reload and review their changes before saving.')
    if register and register.submitted:
        if membership.role != 'head':
            raise PermissionDenied
        if action != 'correct' or not reason.strip():
            raise ValidationError('A school-head correction requires a reason.')
    elif action == 'correct':
        raise ValidationError('Submit the draft before making a correction.')
    if len(reason) > 500:
        raise ValidationError('Use at most 500 characters for the correction reason.')
    rows = roster(group, day, register)
    if not rows:
        raise ValidationError('No eligible learners are enrolled in this class on this date.')
    expected = {str(row['learner'].pk) for row in rows}
    if set(marks) != expected:
        raise ValidationError('The class list has changed or contains an invalid learner. Reload and review before saving.')
    if any(value not in AttendanceEntry.Status.values for value in marks.values()):
        raise ValidationError('Choose a valid attendance status for each learner.')
    if action != 'draft' and any(not value for value in marks.values()):
        raise ValidationError('Mark every learner before submitting or correcting the register.')
    changes = [{'learner_id': row['learner'].pk, 'name': row['learner'].full_name,
                'before': row['status'], 'after': marks[str(row['learner'].pk)]}
               for row in rows if row['status'] != marks[str(row['learner'].pk)]]
    submitted = action in {'submit', 'correct'}
    if register:
        # Compare-and-swap also protects backends where row locks are unavailable.
        updated = AttendanceRegister.objects.filter(pk=register.pk, version=version).update(
            version=version + 1, submitted=submitted, updated_by=membership.user, updated_at=timezone.now())
        if not updated:
            raise StaleRegister('The register changed. Reload before saving.')
        for entry in register.entries.all():
            entry.status = marks[str(entry.learner_id)]
            entry.save(update_fields=['status'])
        register.refresh_from_db()
    else:
        register = AttendanceRegister.objects.create(learning_group=group, date=day, submitted=submitted, updated_by=membership.user)
        AttendanceEntry.objects.bulk_create([AttendanceEntry(register=register, learner=row['learner'], status=marks[str(row['learner'].pk)]) for row in rows])
    AttendanceChange.objects.create(register=register, actor=membership.user, action=action, reason=reason.strip(), changes=changes, version=register.version)
    return register


@school_access()
@require_http_methods(['GET'])
def overview(request):
    error = None
    try:
        day = parse_day(request.GET.get('date'))
    except ValidationError as exc:
        day, error = timezone.localdate(), exc.messages[0]
    groups = scoped_groups(request.membership).filter(academic_year__starts_on__lte=day, academic_year__ends_on__gte=day, active=True)
    registers = {r.learning_group_id: r for r in AttendanceRegister.objects.filter(learning_group__in=groups, date=day).prefetch_related('entries')}
    rows = []
    totals = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'unmarked': 0, 'submitted': 0, 'draft': 0, 'missing': 0}
    for group in groups:
        register = registers.get(group.pk)
        state = ('submitted' if register.submitted else 'draft') if register else 'missing'
        totals[state] += 1
        counts = dict.fromkeys(['present', 'absent', 'late', 'excused', 'unmarked'], 0)
        if register:
            for entry in register.entries.all():
                counts[entry.status or 'unmarked'] += 1
        else:
            counts['unmarked'] = len(eligible_learners(group, day))
        for key, value in counts.items():
            totals[key] += value
        rows.append({'group': group, 'register': register, 'state': state, 'counts': counts})
    return render(request, 'core/attendance_overview.html', {'day':day, 'rows':rows, 'totals':totals, 'error':error,
        'can_open': request.membership.role in {'head','secretary','teacher'}, 'today':timezone.localdate()})


@school_access(allowed_roles={'head', 'secretary', 'teacher'})
@require_http_methods(['GET', 'POST'])
def register_view(request, group_pk, day):
    group = get_object_or_404(scoped_groups(request.membership), pk=group_pk)
    try:
        day = parse_day(day)
    except ValidationError:
        raise Http404
    register = AttendanceRegister.objects.filter(learning_group=group, date=day).first()
    errors = []
    try:
        validate_day(group, day)
    except ValidationError as exc:
        errors.extend(exc.messages)
    can_edit = not errors and (request.membership.role == 'head' or
        (request.membership.role == 'teacher' and not (register and register.submitted)))
    status_code = 200
    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied
        try:
            version = int(request.POST.get('version', '-1'))
            marks = {key[5:]: value for key, value in request.POST.items() if key.startswith('mark_')}
            save_register(request.membership, group, day, version, marks, request.POST.get('action'), request.POST.get('reason', ''))
        except (IntegrityError, OperationalError):
            errors.append('Save was not confirmed because the register was busy. Reload and review before retrying.')
            status_code = 409
            can_edit = False
        except StaleRegister as exc:
            errors.append(str(exc))
            status_code = 409
            can_edit = False
        except (ValueError, ValidationError) as exc:
            errors.extend(exc.messages if isinstance(exc, ValidationError) else ['Invalid form version. Reload the register.'])
        else:
            messages.success(request, 'Attendance saved. ' + ('Register submitted.' if request.POST.get('action') == 'submit' else ''))
            return redirect('attendance_register', group_pk=group.pk, day=day.isoformat())
    rows = roster(group, day, register)
    if request.method == 'POST':
        for row in rows:
            row['status'] = request.POST.get(f"mark_{row['learner'].pk}", row['status'])
    return render(request, 'core/attendance_register.html', {'group':group, 'day':day, 'register':register,
        'rows':rows, 'choices':AttendanceEntry.Status.choices, 'errors':errors, 'can_edit':can_edit,
        'version':register.version if register else 0, 'reason':request.POST.get('reason',''),
        'changes':register.changes.select_related('actor') if register else [], 'conflict':status_code == 409}, status=status_code)
