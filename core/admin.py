from django.contrib import admin

from .models import (
    AcademicYear,
    AnnualEnrollment,
    Grade,
    Guardian,
    GuardianLink,
    ImportBatch,
    Learner,
    LearningGroup,
    School,
    SchoolAdmissionCounter,
    SchoolMembership,
    StaffRecord,
    TeacherClassAssignment,
    Term,
)


def superuser_only_has_permission(request):
    return bool(
        request.user.is_active
        and request.user.is_authenticated
        and request.user.is_superuser
    )


# Django admin is an operations console only. Ordinary school members use the
# application views, where every request is resolved through active membership.
admin.site.has_permission = superuser_only_has_permission


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "admission_prefix", "is_active")
    search_fields = ("name", "admission_prefix")


@admin.register(SchoolAdmissionCounter)
class SchoolAdmissionCounterAdmin(admin.ModelAdmin):
    list_display = ("school", "next_number")
    readonly_fields = ("next_number",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StaffRecord)
class StaffRecordAdmin(admin.ModelAdmin):
    list_display = ("full_name", "school", "category", "active")
    list_filter = ("school", "category", "active")
    search_fields = ("first_name", "last_name", "employee_number", "email")


@admin.register(SchoolMembership)
class SchoolMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "role", "active")
    list_filter = ("school", "role", "active")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user", "school", "staff_record")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "starts_on", "ends_on", "is_current")
    list_filter = ("school", "is_current")


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_year", "sequence", "starts_on", "ends_on")
    list_filter = ("academic_year__school",)


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "code", "sort_order", "active")
    list_filter = ("school", "active")
    search_fields = ("name", "code")


@admin.register(LearningGroup)
class LearningGroupAdmin(admin.ModelAdmin):
    list_display = ("__str__", "academic_year", "grade", "name", "active")
    list_filter = ("academic_year__school", "academic_year", "grade", "active")
    search_fields = ("name", "grade__name")


@admin.register(Learner)
class LearnerAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # Registration service is the sole admission-number allocation path.
        return False

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("school",) if obj else ())

    list_display = (
        "full_name",
        "admission_number",
        "school",
        "status",
        "admission_date",
    )
    list_filter = ("school", "status", "gender")
    search_fields = ("first_name", "middle_name", "last_name", "admission_number")
    readonly_fields = (
        "admission_number",
        "creation_token",
        "created_by",
        "created_at",
        "updated_at",
    )


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("full_name", "school", "phone", "email")
    list_filter = ("school",)
    search_fields = ("first_name", "last_name", "phone", "email")


@admin.register(GuardianLink)
class GuardianLinkAdmin(admin.ModelAdmin):
    list_display = ("learner", "guardian", "relationship", "is_primary")
    list_filter = ("learner__school", "relationship", "is_primary")


@admin.register(AnnualEnrollment)
class AnnualEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("learner", "academic_year", "learning_group", "status")
    list_filter = ("academic_year__school", "academic_year", "status")


@admin.register(TeacherClassAssignment)
class TeacherClassAssignmentAdmin(admin.ModelAdmin):
    list_display = ("membership", "learning_group")
    list_filter = ("membership__school", "learning_group__academic_year")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "school",
        "academic_year",
        "status",
        "rows_imported",
        "created_at",
    )
    list_filter = ("school", "academic_year", "status")
    readonly_fields = (
        "token",
        "csv_text",
        "rows_imported",
        "created_at",
        "committed_at",
    )
