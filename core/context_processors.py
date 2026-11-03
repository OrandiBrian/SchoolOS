from .models import SchoolMembership


def school_context(request):
    school = None
    membership = None
    school_id = request.session.get("active_school_id")
    if request.user.is_authenticated and school_id:
        membership = (
            SchoolMembership.objects.select_related("school", "staff_record")
            .filter(
                user=request.user,
                school_id=school_id,
                active=True,
                school__is_active=True,
            )
            .first()
        )
        if membership:
            school = membership.school
    return {"current_school": school, "current_membership": membership}
