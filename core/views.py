import csv
import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import (
    AcademicYearForm,
    AnnualEnrollmentForm,
    GradeForm,
    GuardianLinkCreateForm,
    ImportConfirmForm,
    ImportUploadForm,
    LearnerForm,
    LearningGroupForm,
    MembershipForm,
    NewSchoolAccountForm,
    SchoolForm,
    StaffRecordForm,
    TeacherClassAssignmentForm,
    TermForm,
)
from .models import (
    AcademicYear,
    AnnualEnrollment,
    Grade,
    GuardianLink,
    ImportBatch,
    Learner,
    LearningGroup,
    SchoolMembership,
    StaffRecord,
)
from .permissions import REGISTRATION_ROLES, school_access
from .services import (
    CSV_HEADERS,
    commit_learner_import,
    create_learner,
    possible_duplicate_learners,
    validate_learner_csv,
)


class SchoolOSLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


@login_required
@require_http_methods(["GET", "POST"])
def select_school(request):
    memberships = (
        SchoolMembership.objects.select_related("school")
        .filter(user=request.user, active=True, school__is_active=True)
        .order_by("school__name")
    )
    if not memberships.exists():
        return render(request, "core/no_school.html", status=403)
    if request.method == "POST":
        membership = memberships.filter(school_id=request.POST.get("school_id")).first()
        if not membership:
            messages.error(request, "Choose a school you can access.")
        else:
            request.session["active_school_id"] = membership.school_id
            return redirect("dashboard")
    elif memberships.count() == 1:
        request.session["active_school_id"] = memberships.first().school_id
        return redirect("dashboard")
    return render(request, "core/select_school.html", {"memberships": memberships})


def _current_year(school):
    return (
        AcademicYear.objects.filter(school=school)
        .order_by("-is_current", "-starts_on")
        .first()
    )


@school_access()
def dashboard(request):
    school = request.school
    membership = request.membership
    current_year = _current_year(school)
    role = membership.role
    context = {
        "current_year": current_year,
        "learner_count": Learner.objects.filter(
            school=school, status=Learner.Status.ACTIVE
        ).count(),
        "enrollment_count": AnnualEnrollment.objects.filter(
            academic_year__school=school,
            academic_year=current_year,
            status=AnnualEnrollment.Status.ACTIVE,
        ).count()
        if current_year
        else 0,
        "group_count": LearningGroup.objects.filter(
            academic_year__school=school, academic_year=current_year
        ).count()
        if current_year
        else 0,
        "active_staff_count": StaffRecord.objects.filter(
            school=school, active=True
        ).count(),
        "role": role,
    }
    if role in {
        SchoolMembership.Role.HEAD,
        SchoolMembership.Role.SECRETARY,
    }:
        context["recent_learners"] = (
            Learner.objects.filter(school=school)
            .prefetch_related(
                Prefetch(
                    "enrollments",
                    queryset=AnnualEnrollment.objects.filter(
                        academic_year=current_year
                    )
                    .select_related("learning_group__grade")
                    .order_by("id"),
                    to_attr="current_enrollments",
                )
            )
            .order_by("-created_at")[:5]
        )
    elif role == SchoolMembership.Role.TEACHER:
        context["assigned_groups"] = (
            LearningGroup.objects.filter(
                teacher_assignments__membership=membership
            )
            .select_related("academic_year", "grade")
            .annotate(
                active_learners=Count(
                    "enrollments",
                    filter=Q(
                        enrollments__status=AnnualEnrollment.Status.ACTIVE
                    ),
                    distinct=True,
                )
            )
        )
    else:
        if current_year:
            context["grade_summary"] = (
                Grade.objects.filter(school=school, active=True)
                .annotate(
                    learner_total=Count(
                        "learning_groups__enrollments",
                        filter=Q(
                            learning_groups__academic_year=current_year,
                            learning_groups__enrollments__status=(
                                AnnualEnrollment.Status.ACTIVE
                            ),
                        ),
                        distinct=True,
                    )
                )
                .order_by("sort_order")
            )
        else:
            context["grade_summary"] = []
    context["show_people"] = role in {
        SchoolMembership.Role.HEAD,
        SchoolMembership.Role.SECRETARY,
    }
    return render(request, "core/dashboard.html", context)


def _teacher_learner_queryset(membership):
    return Learner.objects.filter(
        school=membership.school,
        enrollments__status=AnnualEnrollment.Status.ACTIVE,
        enrollments__academic_year__is_current=True,
        enrollments__learning_group__teacher_assignments__membership=membership
    ).distinct()


@school_access(
    allowed_roles={
        SchoolMembership.Role.HEAD,
        SchoolMembership.Role.SECRETARY,
        SchoolMembership.Role.TEACHER,
    }
)
def learner_list(request):
    membership = request.membership
    learners = Learner.objects.filter(school=request.school)
    if membership.role == SchoolMembership.Role.TEACHER:
        learners = _teacher_learner_queryset(membership)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        learners = learners.filter(
            Q(first_name__icontains=query)
            | Q(middle_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(preferred_name__icontains=query)
            | Q(admission_number__icontains=query)
        )
    if status in Learner.Status.values:
        learners = learners.filter(status=status)

    current_year = _current_year(request.school)
    learners = learners.prefetch_related(
        Prefetch(
            "enrollments",
            queryset=AnnualEnrollment.objects.filter(academic_year=current_year)
            .select_related("learning_group__grade")
            .order_by("id"),
            to_attr="current_enrollments",
        )
    ).order_by("last_name", "first_name")

    context = {
        "query": query,
        "selected_status": status,
        "learners": learners,
        "can_manage": membership.role in REGISTRATION_ROLES,
        "current_year": current_year,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "core/partials/learner_results.html", context)
    return render(request, "core/learner_list.html", context)


def _teacher_can_view_learner(membership, learner):
    return AnnualEnrollment.objects.filter(
        learner=learner,
        status=AnnualEnrollment.Status.ACTIVE,
        academic_year__is_current=True,
        learning_group__teacher_assignments__membership=membership,
    ).exists()


@school_access(
    allowed_roles={
        SchoolMembership.Role.HEAD,
        SchoolMembership.Role.SECRETARY,
        SchoolMembership.Role.TEACHER,
    }
)
def learner_detail(request, pk):
    learner = get_object_or_404(Learner, pk=pk, school=request.school)
    if request.membership.role == SchoolMembership.Role.TEACHER and not (
        _teacher_can_view_learner(request.membership, learner)
    ):
        raise Http404
    return render(
        request,
        "core/learner_detail.html",
        {
            "learner": learner,
            "guardian_links": learner.guardian_links.select_related("guardian"),
            "enrollments": learner.enrollments.select_related(
                "academic_year", "learning_group__grade"
            ).order_by("-academic_year__starts_on"),
            "can_manage": request.membership.role in REGISTRATION_ROLES,
        },
    )


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_http_methods(["GET", "POST"])
def learner_create(request):
    form = LearnerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        token = data.pop("submission_token", None) or uuid.uuid4()
        reviewed = data.pop("duplicate_reviewed", False)
        candidates = possible_duplicate_learners(
            request.school,
            data["first_name"],
            data["last_name"],
            data.get("date_of_birth"),
        )
        if candidates.exists() and not reviewed:
            form.add_error(
                "duplicate_reviewed",
                "Review the possible duplicate learners below before creating this record.",
            )
        else:
            try:
                learner, created = create_learner(
                    request.school,
                    request.user,
                    data,
                    creation_token=token,
                )
            except IntegrityError:
                form.add_error(
                    None,
                    "This submission could not be completed because it conflicted "
                    "with another request. Refresh before trying again.",
                )
            else:
                if created:
                    messages.success(
                        request,
                        f"{learner.full_name} was registered as {learner.admission_number}.",
                    )
                else:
                    messages.info(
                        request, "This registration was already completed."
                    )
                return redirect("learner_detail", pk=learner.pk)
    candidates = possible_duplicate_learners(
        request.school,
        request.POST.get("first_name", ""),
        request.POST.get("last_name", ""),
        request.POST.get("date_of_birth") or None,
    )
    return render(
        request,
        "core/learner_form.html",
        {"form": form, "possible_duplicates": candidates[:5], "is_create": True},
    )


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_http_methods(["GET", "POST"])
def learner_edit(request, pk):
    learner = get_object_or_404(Learner, pk=pk, school=request.school)
    form = LearnerForm(request.POST or None, instance=learner)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Learner details updated.")
        return redirect("learner_detail", pk=learner.pk)
    return render(
        request,
        "core/learner_form.html",
        {
            "form": form,
            "learner": learner,
            "is_create": False,
            "admission_number": learner.admission_number,
        },
    )


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_GET
def duplicate_check(request):
    candidates = possible_duplicate_learners(
        request.school,
        request.GET.get("first_name", ""),
        request.GET.get("last_name", ""),
        request.GET.get("date_of_birth") or None,
    )
    return render(
        request,
        "core/partials/duplicate_check.html",
        {"possible_duplicates": candidates[:5]},
    )


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_http_methods(["GET", "POST"])
def guardian_add(request, pk):
    learner = get_object_or_404(Learner, pk=pk, school=request.school)
    form = GuardianLinkCreateForm(
        request.POST or None, school=request.school
    )
    if request.method == "POST" and form.is_valid():
        try:
            form.save(learner)
        except (IntegrityError, ValidationError):
            form.add_error(None, "This guardian is already linked or the details are invalid.")
        else:
            messages.success(request, "Guardian linked.")
            return redirect("learner_detail", pk=learner.pk)
    return render(
        request,
        "core/guardian_form.html",
        {"learner": learner, "form": form},
    )


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_POST
def guardian_unlink(request, pk, link_pk):
    learner = get_object_or_404(Learner, pk=pk, school=request.school)
    link = get_object_or_404(
        GuardianLink, pk=link_pk, learner=learner, guardian__school=request.school
    )
    link.delete()
    messages.success(request, "Guardian link removed. The guardian record was kept.")
    return redirect("learner_detail", pk=learner.pk)


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_http_methods(["GET", "POST"])
def enrollment_add(request, pk):
    learner = get_object_or_404(Learner, pk=pk, school=request.school)
    form = AnnualEnrollmentForm(
        request.POST or None, school=request.school, learner=learner
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error(
                None,
                "This learner already has an enrolment for that academic year.",
            )
        else:
            messages.success(request, "Annual enrolment recorded.")
            return redirect("learner_detail", pk=learner.pk)
    return render(
        request,
        "core/enrollment_form.html",
        {"learner": learner, "form": form},
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def school_settings(request):
    form = SchoolForm(request.POST or None, instance=request.school)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "School configuration updated.")
        return redirect("school_settings")
    return render(request, "core/school_settings.html", {"form": form})


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_GET
def academics(request):
    return render(
        request,
        "core/academics.html",
        {
            "years": AcademicYear.objects.filter(school=request.school)
            .prefetch_related("terms", "learning_groups__grade")
            .order_by("-starts_on"),
            "grades": Grade.objects.filter(school=request.school).order_by(
                "sort_order"
            ),
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def academic_year_create(request):
    form = AcademicYearForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                year = form.save(commit=False)
                year.school = request.school
                if year.is_current:
                    AcademicYear.objects.filter(
                        school=request.school, is_current=True
                    ).update(is_current=False)
                year.full_clean()
                year.save()
                messages.success(request, "Academic year created. Add its terms and streams.")
                return redirect("academics")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, "Please check these values for duplicates or invalid dates.")

    return render(
        request,
        "core/form_page.html",
        {"form": form, "title": "Add academic year", "cancel_url": "academics"},
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def term_create(request, year_pk):
    year = get_object_or_404(
        AcademicYear, pk=year_pk, school=request.school
    )
    form = TermForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                term = form.save(commit=False)
                term.academic_year = year
                term.full_clean()
                term.save()
                messages.success(request, "Term added.")
                return redirect("academics")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, "Please check these values for duplicates or invalid dates.")

    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": f"Add a term to {year}",
            "cancel_url": "academics",
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def grade_create(request):
    form = GradeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                grade = form.save(commit=False)
                grade.school = request.school
                grade.full_clean()
                grade.save()
                messages.success(request, "Grade added.")
                return redirect("academics")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, "Please check these values for duplicates or invalid dates.")

    return render(
        request,
        "core/form_page.html",
        {"form": form, "title": "Add grade", "cancel_url": "academics"},
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def group_create(request, year_pk):
    year = get_object_or_404(
        AcademicYear, pk=year_pk, school=request.school
    )
    form = LearningGroupForm(
        request.POST or None, school=request.school, academic_year=year
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                group = form.save(commit=False)
                group.academic_year = year
                group.full_clean()
                group.save()
                messages.success(request, "Class and stream added.")
                return redirect("academics")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, "Please check these values for duplicates or invalid dates.")

    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": f"Add a class to {year}",
            "cancel_url": "academics",
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_GET
def staff_list(request):
    return render(
        request,
        "core/staff_list.html",
        {
            "staff_records": StaffRecord.objects.filter(
                school=request.school
            ).order_by("category", "last_name", "first_name"),
            "memberships": SchoolMembership.objects.filter(
                school=request.school
            )
            .select_related("user", "staff_record")
            .order_by("user__username"),
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def staff_create(request):
    form = StaffRecordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                staff = form.save(commit=False)
                staff.school = request.school
                staff.full_clean()
                staff.save()
                messages.success(
                    request, "Staff record saved. This does not create a login."
                )
                return redirect("staff_list")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, "Please check these values for duplicates or invalid dates.")

    return render(
        request,
        "core/form_page.html",
        {"form": form, "title": "Add staff record", "cancel_url": "staff_list"},
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def staff_edit(request, pk):
    staff = get_object_or_404(StaffRecord, pk=pk, school=request.school)
    form = StaffRecordForm(request.POST or None, instance=staff)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Staff record updated.")
        return redirect("staff_list")
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": f"Edit {staff.full_name}",
            "cancel_url": "staff_list",
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def membership_create(request):
    form = NewSchoolAccountForm(request.POST or None, school=request.school)
    if request.method == "POST" and form.is_valid():
        membership = form.save()
        messages.success(request, "School access assigned.")
        if membership.role == SchoolMembership.Role.TEACHER:
            return redirect("teacher_classes", pk=membership.pk)
        return redirect("staff_list")
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": "Assign school access",
            "cancel_url": "staff_list",
            "help_text": (
                "Create an individual account for this school. Staff records do not automatically grant access."
            ),
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def membership_edit(request, pk):
    membership = get_object_or_404(
        SchoolMembership, pk=pk, school=request.school
    )
    form = MembershipForm(
        request.POST or None, instance=membership, school=request.school
    )
    if request.method == "POST" and form.is_valid():
        membership = form.save()
        messages.success(request, "School access updated.")
        if membership.role == SchoolMembership.Role.TEACHER:
            return redirect("teacher_classes", pk=membership.pk)
        return redirect("staff_list")
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": "Edit school access",
            "cancel_url": "staff_list",
        },
    )


@school_access(allowed_roles={SchoolMembership.Role.HEAD})
@require_http_methods(["GET", "POST"])
def teacher_classes(request, pk):
    membership = get_object_or_404(
        SchoolMembership,
        pk=pk,
        school=request.school,
        role=SchoolMembership.Role.TEACHER,
    )
    form = TeacherClassAssignmentForm(
        request.POST or None, school=request.school, membership=membership
    )
    if request.method == "POST" and form.is_valid():
        count = form.save()
        messages.success(request, f"{count} class assignment(s) saved.")
        return redirect("staff_list")
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": (
                "Classes for "
                f"{membership.user.get_full_name() or membership.user.username}"
            ),
            "cancel_url": "staff_list",
        },
    )


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_http_methods(["GET", "POST"])
def import_upload(request):
    form = ImportUploadForm(
        request.POST or None, request.FILES or None, school=request.school
    )
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["file"]
        try:
            csv_text = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            form.add_error("file", "The CSV must be UTF-8 encoded.")
        else:
            batch = ImportBatch.objects.create(
                school=request.school,
                academic_year=form.cleaned_data["academic_year"],
                original_filename=uploaded.name[:255],
                csv_text=csv_text,
                created_by=request.user,
            )
            return redirect("import_preview", token=batch.token)
    return render(request, "core/import_upload.html", {"form": form})


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_GET
def import_template(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="schoolos-learner-import-template.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(CSV_HEADERS)
    writer.writerow(
        [
            "Amina",
            "",
            "Otieno",
            "Ami",
            "2018-04-12",
            "female",
            "2027-01-05",
            "PP1",
            "A",
            "Mary",
            "Otieno",
            "Mother",
            "+254700000000",
            "mary@example.test",
        ]
    )
    return response


@school_access(allowed_roles=REGISTRATION_ROLES)
@require_http_methods(["GET", "POST"])
def import_preview(request, token):
    batch = get_object_or_404(
        ImportBatch,
        token=token,
        school=request.school,
        academic_year__school=request.school,
    )
    if batch.status == ImportBatch.Status.COMMITTED:
        return render(
            request,
            "core/import_committed.html",
            {"batch": batch},
        )
    preview = validate_learner_csv(
        request.school, batch.academic_year, batch.csv_text
    )
    confirm_form = ImportConfirmForm(request.POST or None)
    if request.method == "POST":
        if not preview.valid:
            messages.error(request, "Fix the CSV errors and upload a new file.")
        elif preview.duplicate_rows and not confirm_form.is_valid():
            messages.error(request, "Review the possible duplicates before importing.")
        elif preview.duplicate_rows and not confirm_form.cleaned_data[
            "confirm_possible_duplicates"
        ]:
            messages.error(request, "Mark possible duplicates as reviewed.")
        else:
            try:
                commit_learner_import(batch, batch.academic_year, request.user)
            except (ValueError, IntegrityError, ValidationError):
                messages.error(request, "Nothing was imported. Check the file values and class configuration, then upload again.")
            else:
                messages.success(
                    request,
                    f"{batch.rows_imported} learners imported successfully.",
                )
                return redirect("import_preview", token=batch.token)
    return render(
        request,
        "core/import_preview.html",
        {
            "batch": batch,
            "preview": preview,
            "confirm_form": confirm_form,
        },
    )
