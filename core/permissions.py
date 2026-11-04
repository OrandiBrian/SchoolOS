from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import SchoolMembership


def active_membership(user, school_id):
    return (
        SchoolMembership.objects.select_related("school", "staff_record")
        .filter(user=user, user__is_active=True, school_id=school_id, active=True, school__is_active=True)
        .first()
    )


def school_access(allowed_roles=None):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            school_id = request.session.get("active_school_id")
            membership = (
                active_membership(request.user, school_id) if school_id else None
            )
            if not membership:
                request.session.pop("active_school_id", None)
                return redirect("select_school")
            if allowed_roles and membership.role not in allowed_roles:
                raise PermissionDenied
            request.school = membership.school
            request.membership = membership
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


REGISTRATION_ROLES = {
    SchoolMembership.Role.HEAD,
    SchoolMembership.Role.SECRETARY,
}
TEACHER_ROLES = {SchoolMembership.Role.TEACHER}
SUMMARY_ROLES = {
    SchoolMembership.Role.HEAD,
    SchoolMembership.Role.SECRETARY,
    SchoolMembership.Role.DIRECTOR,
    SchoolMembership.Role.BOARD,
}


def raise_for_unassigned_teacher(membership):
    if membership.role != SchoolMembership.Role.TEACHER:
        return
    if not membership.teacher_class_assignments.exists():
        raise PermissionDenied
