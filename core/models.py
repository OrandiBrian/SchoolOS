import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


prefix_validator = RegexValidator(
    regex=r"^[A-Z][A-Z0-9]{1,11}$",
    message="Use 2-12 uppercase letters or digits, starting with a letter.",
)


class School(models.Model):
    name = models.CharField(max_length=160)
    admission_prefix = models.CharField(
        max_length=12, default="LCCS", validators=[prefix_validator]
    )
    motto = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        self.admission_prefix = self.admission_prefix.upper()
        if self.pk:
            old_prefix = (
                School.objects.filter(pk=self.pk)
                .values_list("admission_prefix", flat=True)
                .first()
            )
            if (
                old_prefix
                and old_prefix != self.admission_prefix
                and Learner.objects.filter(school_id=self.pk).exists()
            ):
                raise ValidationError(
                    {
                        "admission_prefix": (
                            "The admission prefix cannot change after learner "
                            "numbers have been issued."
                        )
                    }
                )


class SchoolAdmissionCounter(models.Model):
    school = models.OneToOneField(
        School, on_delete=models.CASCADE, related_name="admission_counter"
    )
    next_number = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(next_number__gte=1),
                name="school_next_admission_positive",
            )
        ]

    def __str__(self):
        return f"{self.school}: next {self.next_number}"


class StaffRecord(models.Model):
    class Category(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        SECRETARY = "secretary", "Secretary"
        HEAD = "head", "School head"
        DIRECTOR = "director", "Director"
        BOARD = "board", "Board member"
        SUPPORT = "support", "Non-teaching staff"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="staff_records"
    )
    first_name = models.CharField(max_length=80)
    middle_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80)
    category = models.CharField(max_length=20, choices=Category.choices)
    employee_number = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "employee_number"],
                condition=~Q(employee_number=""),
                name="unique_staff_number_per_school",
            )
        ]

    @property
    def full_name(self):
        return " ".join(
            part for part in [self.first_name, self.middle_name, self.last_name] if part
        )

    def __str__(self):
        return self.full_name


class SchoolMembership(models.Model):
    class Role(models.TextChoices):
        HEAD = "head", "School head"
        SECRETARY = "secretary", "Secretary"
        TEACHER = "teacher", "Teacher"
        DIRECTOR = "director", "Director"
        BOARD = "board", "Board aggregate reader"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="school_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    staff_record = models.ForeignKey(
        StaffRecord,
        on_delete=models.PROTECT,
        related_name="memberships",
        null=True,
        blank=True,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["school__name", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "user"], name="one_school_role_per_user"
            )
        ]

    def clean(self):
        if self.staff_record_id and self.staff_record.school_id != self.school_id:
            raise ValidationError(
                {"staff_record": "The staff record must belong to the same school."}
            )

    def __str__(self):
        return f"{self.user} - {self.get_role_display()} at {self.school}"


class AcademicYear(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="academic_years"
    )
    name = models.CharField(max_length=40)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_on", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"], name="unique_year_name_per_school"
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=Q(is_current=True),
                name="one_current_year_per_school",
            ),
            models.CheckConstraint(
                check=Q(ends_on__gt=models.F("starts_on")),
                name="academic_year_end_after_start",
            ),
        ]

    def clean(self):
        if self.starts_on and self.ends_on and self.ends_on <= self.starts_on:
            raise ValidationError({"ends_on": "The year must end after it starts."})

    def __str__(self):
        return self.name


class Term(models.Model):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="terms"
    )
    name = models.CharField(max_length=60)
    starts_on = models.DateField()
    ends_on = models.DateField()
    sequence = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["academic_year", "sequence", "starts_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "name"],
                name="unique_term_name_per_year",
            ),
            models.UniqueConstraint(
                fields=["academic_year", "sequence"],
                name="unique_term_sequence_per_year",
            ),
            models.CheckConstraint(
                check=Q(ends_on__gt=models.F("starts_on")),
                name="term_end_after_start",
            ),
        ]

    @property
    def school(self):
        return self.academic_year.school

    def clean(self):
        if not self.academic_year_id:
            return
        if self.starts_on and self.starts_on < self.academic_year.starts_on:
            raise ValidationError(
                {"starts_on": "A term cannot start before the academic year."}
            )
        if self.ends_on and self.ends_on > self.academic_year.ends_on:
            raise ValidationError(
                {"ends_on": "A term cannot end after the academic year."}
            )
        if self.starts_on and self.ends_on and self.ends_on <= self.starts_on:
            raise ValidationError({"ends_on": "The term must end after it starts."})

    def __str__(self):
        return f"{self.academic_year}: {self.name}"


class Grade(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="grades"
    )
    name = models.CharField(max_length=40)
    code = models.CharField(max_length=20)
    sort_order = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"], name="unique_grade_name_per_school"
            ),
            models.UniqueConstraint(
                fields=["school", "code"], name="unique_grade_code_per_school"
            ),
        ]

    def __str__(self):
        return self.name


class LearningGroup(models.Model):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="learning_groups"
    )
    grade = models.ForeignKey(
        Grade, on_delete=models.PROTECT, related_name="learning_groups"
    )
    name = models.CharField(max_length=40)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["academic_year", "grade__sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "grade", "name"],
                name="unique_group_per_year_grade",
            )
        ]

    @property
    def school(self):
        return self.academic_year.school

    def clean(self):
        if (
            self.academic_year_id
            and self.grade_id
            and self.academic_year.school_id != self.grade.school_id
        ):
            raise ValidationError(
                {"grade": "The grade and academic year must belong to the same school."}
            )

    def __str__(self):
        return f"{self.grade} {self.name} ({self.academic_year})"


class Learner(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other / prefer not to say"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        WITHDRAWN = "withdrawn", "Withdrawn"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="learners"
    )
    admission_number = models.CharField(max_length=32, blank=True)
    first_name = models.CharField(max_length=80)
    middle_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80)
    preferred_name = models.CharField(max_length=80, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=20, choices=Gender.choices, blank=True
    )
    admission_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField(blank=True)
    creation_token = models.UUIDField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learners_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name", "admission_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "admission_number"],
                condition=~Q(admission_number=""),
                name="unique_admission_number_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "creation_token"],
                condition=Q(creation_token__isnull=False),
                name="unique_creation_token_per_school",
            ),
        ]

    @property
    def full_name(self):
        return " ".join(
            part for part in [self.first_name, self.middle_name, self.last_name] if part
        )

    @property
    def display_name(self):
        return self.preferred_name or self.first_name

    def clean(self):
        if self.admission_number and not re.fullmatch(
            r"[A-Z0-9]{2,12}-\d{6,}", self.admission_number
        ):
            raise ValidationError(
                {"admission_number": "Admission numbers must use PREFIX-000001."}
            )
        if (
            self.admission_number
            and self.school_id
            and not self.admission_number.startswith(
                f"{self.school.admission_prefix}-"
            )
        ):
            raise ValidationError(
                {
                    "admission_number": (
                        f"Admission numbers for this school begin with "
                        f"{self.school.admission_prefix}-."
                    )
                }
            )

    def __str__(self):
        return f"{self.full_name} ({self.admission_number or 'No number'})"


class TeacherClassAssignment(models.Model):
    membership = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="teacher_class_assignments",
    )
    learning_group = models.ForeignKey(
        LearningGroup, on_delete=models.PROTECT, related_name="teacher_assignments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["membership__user__username", "learning_group"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "learning_group"],
                name="unique_teacher_class_assignment",
            )
        ]

    def clean(self):
        if not self.membership_id or not self.learning_group_id:
            return
        if self.membership.role != SchoolMembership.Role.TEACHER:
            raise ValidationError(
                {"membership": "Only teacher memberships can be assigned classes."}
            )
        if self.membership.school_id != self.learning_group.academic_year.school_id:
            raise ValidationError(
                {"learning_group": "The class must belong to the teacher's school."}
            )

    def __str__(self):
        return f"{self.membership.user} - {self.learning_group}"


class Guardian(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="guardians"
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=40, blank=True)
    alternate_phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["school", "last_name", "first_name"]),
            models.Index(fields=["school", "phone"]),
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class GuardianLink(models.Model):
    learner = models.ForeignKey(
        Learner, on_delete=models.PROTECT, related_name="guardian_links"
    )
    guardian = models.ForeignKey(
        Guardian, on_delete=models.PROTECT, related_name="learner_links"
    )
    relationship = models.CharField(max_length=60)
    is_primary = models.BooleanField(default=False)
    can_receive_school_communications = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "guardian__last_name", "guardian__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "guardian"],
                name="unique_guardian_link",
            )
        ]

    def clean(self):
        if not self.learner_id or not self.guardian_id:
            return
        if self.learner.school_id != self.guardian.school_id:
            raise ValidationError("Guardians and learners must belong to the same school.")

    def __str__(self):
        return f"{self.guardian} ({self.relationship}) - {self.learner}"


class AnnualEnrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WITHDRAWN = "withdrawn", "Withdrawn"
        COMPLETED = "completed", "Completed"

    learner = models.ForeignKey(
        Learner, on_delete=models.PROTECT, related_name="enrollments"
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="enrollments"
    )
    learning_group = models.ForeignKey(
        LearningGroup, on_delete=models.PROTECT, related_name="enrollments"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    enrolled_on = models.DateField(default=timezone.localdate)
    withdrawn_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-academic_year__starts_on", "learner__last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "academic_year"],
                name="one_enrollment_per_learner_year",
            )
        ]

    def clean(self):
        if not self.learner_id or not self.academic_year_id or not self.learning_group_id:
            return
        if self.learner.school_id != self.academic_year.school_id:
            raise ValidationError(
                {"academic_year": "The year must belong to the learner's school."}
            )
        if self.learning_group.academic_year_id != self.academic_year_id:
            raise ValidationError(
                {"learning_group": "Choose a class in the selected academic year."}
            )
        if self.learning_group.academic_year.school_id != self.learner.school_id:
            raise ValidationError(
                {"learning_group": "The class must belong to the learner's school."}
            )

    def __str__(self):
        return f"{self.learner} - {self.learning_group}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEW = "preview", "Preview"
        COMMITTED = "committed", "Committed"

    school = models.ForeignKey(
        School, on_delete=models.PROTECT, related_name="learner_import_batches"
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="learner_import_batches"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    original_filename = models.CharField(max_length=255)
    csv_text = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PREVIEW
    )
    rows_imported = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learner_imports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.get_status_display()})"


class AttendanceRegister(models.Model):
    learning_group = models.ForeignKey(LearningGroup, on_delete=models.PROTECT, related_name='attendance_registers')
    date = models.DateField()
    submitted = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-date']
        constraints = [models.UniqueConstraint(fields=['learning_group', 'date'], name='one_attendance_register_per_class_date')]


class AttendanceEntry(models.Model):
    class Status(models.TextChoices):
        UNMARKED = '', 'Unmarked'
        PRESENT = 'present', 'Present'
        ABSENT = 'absent', 'Absent'
        LATE = 'late', 'Late'
        EXCUSED = 'excused', 'Excused'

    register = models.ForeignKey(AttendanceRegister, on_delete=models.PROTECT, related_name='entries')
    learner = models.ForeignKey(Learner, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=Status.choices, blank=True)

    class Meta:
        ordering = ['learner__last_name', 'learner__first_name']
        constraints = [models.UniqueConstraint(fields=['register', 'learner'], name='one_attendance_entry_per_register_learner')]


class AttendanceChange(models.Model):
    register = models.ForeignKey(AttendanceRegister, on_delete=models.PROTECT, related_name='changes')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=16)
    reason = models.CharField(max_length=500, blank=True)
    changes = models.JSONField(default=list)
    version = models.PositiveIntegerField()

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['register', 'version'], name='one_attendance_change_per_version')]
