import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AcademicYear,
    AnnualEnrollment,
    Grade,
    Guardian,
    GuardianLink,
    Learner,
    LearningGroup,
    School,
    SchoolMembership,
    StaffRecord,
    TeacherClassAssignment,
    Term,
)


class StyledFormMixin:
    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            css = "form-input"
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                css = "form-checkbox"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            elif isinstance(widget, forms.Textarea):
                css = "form-textarea"
            widget.attrs["class"] = (
                f'{widget.attrs.get("class", "")} {css}'.strip()
            )


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class StyledForm(StyledFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class SchoolForm(StyledModelForm):
    class Meta:
        model = School
        fields = ["name", "admission_prefix", "motto", "address", "phone", "email"]


class StaffRecordForm(StyledModelForm):
    class Meta:
        model = StaffRecord
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "category",
            "employee_number",
            "email",
            "phone",
            "active",
            "notes",
        ]


class AcademicYearForm(StyledModelForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "starts_on", "ends_on", "is_current"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }


class TermForm(StyledModelForm):
    class Meta:
        model = Term
        fields = ["name", "starts_on", "ends_on", "sequence"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }


class GradeForm(StyledModelForm):
    class Meta:
        model = Grade
        fields = ["name", "code", "sort_order", "active"]


class LearningGroupForm(StyledModelForm):
    def __init__(self, *args, school, academic_year=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grade"].queryset = Grade.objects.filter(
            school=school, active=True
        )
        if academic_year is not None:
            self.instance.academic_year = academic_year

    class Meta:
        model = LearningGroup
        fields = ["grade", "name", "capacity", "active"]


class LearnerForm(StyledModelForm):
    submission_token = forms.UUIDField(required=False, widget=forms.HiddenInput)
    duplicate_reviewed = forms.BooleanField(
        required=False,
        label="I reviewed the possible duplicate warning",
        widget=forms.CheckboxInput,
    )

    class Meta:
        model = Learner
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "preferred_name",
            "date_of_birth",
            "gender",
            "admission_date",
            "status",
            "notes",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "admission_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get("submission_token"):
            self.initial["submission_token"] = uuid.uuid4()


class GuardianLinkCreateForm(StyledForm):
    guardian = forms.ModelChoiceField(
        queryset=Guardian.objects.none(),
        required=False,
        label="Existing guardian",
        help_text="Choose an existing guardian or enter a new guardian below.",
    )
    first_name = forms.CharField(max_length=80, required=False)
    last_name = forms.CharField(max_length=80, required=False)
    phone = forms.CharField(max_length=40, required=False)
    alternate_phone = forms.CharField(max_length=40, required=False)
    email = forms.EmailField(required=False)
    relationship = forms.CharField(max_length=60)
    is_primary = forms.BooleanField(required=False)
    can_receive_school_communications = forms.BooleanField(
        required=False, initial=True
    )

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["guardian"].queryset = Guardian.objects.filter(
            school=school
        ).order_by("last_name", "first_name")

    def clean(self):
        cleaned = super().clean()
        guardian = cleaned.get("guardian")
        if not guardian and not (
            cleaned.get("first_name") and cleaned.get("last_name")
        ):
            raise ValidationError(
                "Choose an existing guardian or enter the new guardian's first and last name."
            )
        return cleaned

    @transaction.atomic
    def save(self, learner):
        data = self.cleaned_data
        guardian = data.get("guardian") or Guardian(
            school=learner.school,
            first_name=data["first_name"],
            last_name=data["last_name"],
            phone=data.get("phone", ""),
            alternate_phone=data.get("alternate_phone", ""),
            email=data.get("email", ""),
        )
        guardian.full_clean()
        guardian.save()
        if data.get("is_primary"):
            learner.guardian_links.update(is_primary=False)
        link = GuardianLink(
            learner=learner,
            guardian=guardian,
            relationship=data["relationship"],
            is_primary=data.get("is_primary", False),
            can_receive_school_communications=data.get(
                "can_receive_school_communications", False
            ),
        )
        link.full_clean()
        link.save()
        return link


class AnnualEnrollmentForm(StyledModelForm):
    def __init__(self, *args, school, learner, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.learner = learner
        self.fields["academic_year"].queryset = AcademicYear.objects.filter(
            school=school
        ).order_by("-starts_on")
        self.fields["learning_group"].queryset = (
            LearningGroup.objects.filter(academic_year__school=school)
            .select_related("academic_year", "grade")
            .order_by("-academic_year__starts_on", "grade__sort_order", "name")
        )

    class Meta:
        model = AnnualEnrollment
        fields = [
            "academic_year",
            "learning_group",
            "status",
            "enrolled_on",
            "withdrawn_on",
            "notes",
        ]
        widgets = {
            "enrolled_on": forms.DateInput(attrs={"type": "date"}),
            "withdrawn_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class MembershipForm(StyledModelForm):
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if self.instance.pk:
            self.fields["user"].queryset = User.objects.filter(
                pk=self.instance.user_id
            )
        else:
            self.fields["user"].queryset = User.objects.none()
        self.fields["staff_record"].queryset = StaffRecord.objects.filter(
            school=school, active=True
        )
        self.instance.school = school

    class Meta:
        model = SchoolMembership
        fields = ["user", "role", "staff_record", "active"]


class TeacherClassAssignmentForm(StyledForm):
    classes = forms.ModelMultipleChoiceField(
        queryset=LearningGroup.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def __init__(self, *args, school, membership, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership
        self.fields["classes"].queryset = (
            LearningGroup.objects.filter(academic_year__school=school)
            .select_related("academic_year", "grade")
            .order_by("-academic_year__starts_on", "grade__sort_order", "name")
        )
        if not self.is_bound:
            self.initial["classes"] = LearningGroup.objects.filter(
                teacher_assignments__membership=membership
            )

    @transaction.atomic
    def save(self):
        selected = self.cleaned_data["classes"]
        TeacherClassAssignment.objects.filter(membership=self.membership).exclude(
            learning_group__in=selected
        ).delete()
        for group in selected:
            assignment = TeacherClassAssignment(
                membership=self.membership, learning_group=group
            )
            assignment.clean()
            TeacherClassAssignment.objects.get_or_create(
                membership=self.membership, learning_group=group
            )
        return len(selected)


class ImportUploadForm(StyledForm):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.none())
    file = forms.FileField(
        help_text="CSV only, up to 2 MB and 500 learner rows.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["academic_year"].queryset = AcademicYear.objects.filter(
            school=school
        ).order_by("-starts_on")

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise ValidationError("Upload a .csv file.")
        if uploaded.size > 2 * 1024 * 1024:
            raise ValidationError("The CSV must be 2 MB or smaller.")
        return uploaded


class ImportConfirmForm(StyledForm):
    confirm_possible_duplicates = forms.BooleanField(
        required=False,
        label="I reviewed every possible duplicate shown below",
    )




class NewSchoolAccountForm(StyledForm):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, help_text="Give the new user this initial password securely.")
    role = forms.ChoiceField(choices=SchoolMembership.Role.choices)
    staff_record = forms.ModelChoiceField(queryset=StaffRecord.objects.none(), required=False)

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["staff_record"].queryset = StaffRecord.objects.filter(school=school, active=True)

    def clean(self):
        data = super().clean()
        user = get_user_model()(username=data.get("username", ""), first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
        try:
            user.full_clean(exclude=["password"])
            if data.get("password"):
                validate_password(data["password"], user)
        except ValidationError as exc:
            self.add_error(None, "Account details are invalid or unavailable. " + ("Choose a stronger password." if not hasattr(exc, "message_dict") else "Choose a different username."))
        return data

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = get_user_model().objects.create_user(username=data["username"], password=data["password"], first_name=data["first_name"], last_name=data["last_name"])
        return SchoolMembership.objects.create(school=self.school, user=user, role=data["role"], staff_record=data.get("staff_record"))
