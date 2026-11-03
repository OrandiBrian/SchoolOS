import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import (
    AnnualEnrollment,
    Grade,
    Guardian,
    GuardianLink,
    Learner,
    LearningGroup,
    School,
    SchoolAdmissionCounter,
)


def normalize_name(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def allocate_admission_number(school):
    """Allocate a never-reused number while holding the school counter lock."""
    with transaction.atomic():
        counter, _ = SchoolAdmissionCounter.objects.get_or_create(school=school)
        counter = SchoolAdmissionCounter.objects.select_for_update().get(pk=counter.pk)
        number = counter.next_number
        counter.next_number = number + 1
        counter.save(update_fields=["next_number"])
    return f"{school.admission_prefix}-{number:06d}"


def create_learner(school, actor, cleaned_data, creation_token=None):
    token = creation_token or uuid.uuid4()
    with transaction.atomic():
        if creation_token:
            existing = Learner.objects.filter(
                school=school, creation_token=creation_token
            ).first()
            if existing:
                return existing, False

        learner = Learner(
            school=school,
            created_by=actor,
            creation_token=token,
            **cleaned_data,
        )
        learner.admission_number = allocate_admission_number(school)
        learner.full_clean()
        learner.save()
        return learner, True


def possible_duplicate_learners(school, first_name, last_name, date_of_birth=None):
    first = normalize_name(first_name)
    last = normalize_name(last_name)
    if not first or not last:
        return Learner.objects.none()
    query = Q(first_name__iexact=first_name) & Q(last_name__iexact=last_name)
    candidates = Learner.objects.filter(school=school).filter(query)
    if isinstance(date_of_birth, str):
        try:
            date_of_birth = date.fromisoformat(date_of_birth)
        except ValueError:
            date_of_birth = None
    if date_of_birth:
        candidates = candidates.filter(
            Q(date_of_birth=date_of_birth) | Q(date_of_birth__isnull=True)
        )
    return candidates


CSV_HEADERS = [
    "first_name",
    "middle_name",
    "last_name",
    "preferred_name",
    "date_of_birth",
    "gender",
    "admission_date",
    "grade",
    "stream",
    "guardian_first_name",
    "guardian_last_name",
    "guardian_relationship",
    "guardian_phone",
    "guardian_email",
]

REQUIRED_CSV_VALUES = ["first_name", "last_name", "admission_date", "grade", "stream"]
GUARDIAN_FIELDS = [
    "guardian_first_name",
    "guardian_last_name",
    "guardian_relationship",
    "guardian_phone",
    "guardian_email",
]


@dataclass
class ImportPreview:
    rows: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    duplicate_rows: set[int] = field(default_factory=set)
    headers: list[str] = field(default_factory=list)

    @property
    def valid(self):
        return not self.errors


def _parse_iso_date(value, label, row_number, errors):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append({"row": row_number, "field": label, "message": "Use YYYY-MM-DD."})
        return None


def validate_learner_csv(school, academic_year, csv_text):
    preview = ImportPreview()
    stream = io.StringIO(csv_text)
    reader = csv.DictReader(stream)
    preview.headers = reader.fieldnames or []
    missing_headers = [header for header in CSV_HEADERS if header not in preview.headers]
    if missing_headers:
        preview.errors.append(
            {
                "row": "header",
                "field": "columns",
                "message": "Missing columns: " + ", ".join(missing_headers),
            }
        )
        return preview

    groups = LearningGroup.objects.filter(
        academic_year=academic_year, academic_year__school=school
    ).select_related("grade")
    group_lookup = {
        (normalize_name(item.grade.name), normalize_name(item.name)): item
        for item in groups
    }
    seen_rows = {}
    for row_number, raw in enumerate(reader, start=2):
        if None in raw:
            preview.errors.append({"row": row_number, "field": "columns", "message": "Too many columns in this row."})
            continue
        if not any((value or "").strip() for value in raw.values()):
            continue
        row = {header: (raw.get(header) or "").strip() for header in CSV_HEADERS}
        row_errors = []
        for required in REQUIRED_CSV_VALUES:
            if not row[required]:
                row_errors.append(
                    {
                        "row": row_number,
                        "field": required,
                        "message": "This value is required.",
                    }
                )

        date_of_birth = _parse_iso_date(
            row["date_of_birth"], "date_of_birth", row_number, row_errors
        )
        admission_date = _parse_iso_date(
            row["admission_date"], "admission_date", row_number, row_errors
        )
        if row["gender"] and row["gender"].lower() not in dict(
            Learner.Gender.choices
        ):
            row_errors.append(
                {
                    "row": row_number,
                    "field": "gender",
                    "message": "Use female, male, or other.",
                }
            )

        group = group_lookup.get(
            (normalize_name(row["grade"]), normalize_name(row["stream"]))
        )
        if row["grade"] and row["stream"] and not group:
            row_errors.append(
                {
                    "row": row_number,
                    "field": "grade / stream",
                    "message": (
                        "No matching class exists in the selected academic year."
                    ),
                }
            )

        guardian_values = [row[field] for field in GUARDIAN_FIELDS]
        guardian_started = any(guardian_values)
        if guardian_started:
            for required in [
                "guardian_first_name",
                "guardian_last_name",
                "guardian_relationship",
            ]:
                if not row[required]:
                    row_errors.append(
                        {
                            "row": row_number,
                            "field": required,
                            "message": (
                                "Required when any guardian details are supplied."
                            ),
                        }
                    )

        learner_probe = Learner(school=school, first_name=row["first_name"], middle_name=row["middle_name"], last_name=row["last_name"], preferred_name=row["preferred_name"], date_of_birth=date_of_birth, gender=row["gender"].lower(), admission_date=admission_date)
        probes = [learner_probe]
        if guardian_started:
            probes.append(Guardian(school=school, first_name=row["guardian_first_name"], last_name=row["guardian_last_name"], phone=row["guardian_phone"], email=row["guardian_email"]))
            if len(row["guardian_relationship"]) > 60:
                row_errors.append({"row": row_number, "field": "guardian_relationship", "message": "Use at most 60 characters."})
        for probe in probes:
            try:
                probe.full_clean()
            except ValidationError as exc:
                for field_name, errors in exc.message_dict.items():
                    row_errors.append({"row": row_number, "field": field_name, "message": " ".join(errors)})

        normalized_key = (
            normalize_name(row["first_name"]),
            normalize_name(row["last_name"]),
            row["date_of_birth"],
        )
        if all(normalized_key):
            if normalized_key in seen_rows:
                row_errors.append(
                    {
                        "row": row_number,
                        "field": "name / date_of_birth",
                        "message": (
                            f"Duplicates row {seen_rows[normalized_key]} in this file."
                        ),
                    }
                )
            else:
                seen_rows[normalized_key] = row_number

        if not row_errors and possible_duplicate_learners(
            school, row["first_name"], row["last_name"], date_of_birth
        ).exists():
            preview.duplicate_rows.add(row_number)

        row["row_number"] = row_number
        row["date_of_birth_value"] = date_of_birth
        row["admission_date_value"] = admission_date
        row["learning_group"] = group
        preview.errors.extend(row_errors)
        preview.rows.append(row)

    if not preview.rows:
        preview.errors.append(
            {"row": "file", "field": "rows", "message": "The file has no data rows."}
        )
    if len(preview.rows) > 500:
        preview.errors.append(
            {
                "row": "file",
                "field": "rows",
                "message": "Import at most 500 learners at a time.",
            }
        )
    return preview


def _find_or_create_guardian(school, row):
    if not row["guardian_first_name"]:
        return None
    # Imported contact details are not proof of identity. Create separate records;
    # staff can explicitly link an existing guardian after reviewing the family.
    guardian = Guardian(
        school=school,
        first_name=row["guardian_first_name"],
        last_name=row["guardian_last_name"],
        phone=row["guardian_phone"],
        email=row["guardian_email"],
    )
    guardian.full_clean()
    guardian.save()
    return guardian


@transaction.atomic
def commit_learner_import(batch, academic_year, actor):
    from .models import ImportBatch

    locked = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status == ImportBatch.Status.COMMITTED:
        return locked.rows_imported
    preview = validate_learner_csv(locked.school, academic_year, locked.csv_text)
    if not preview.valid:
        raise ValueError("The import no longer passes validation.")

    for row in preview.rows:
        token = uuid.uuid5(locked.token, str(row["row_number"]))
        learner, _ = create_learner(
            locked.school,
            actor,
            {
                "first_name": row["first_name"],
                "middle_name": row["middle_name"],
                "last_name": row["last_name"],
                "preferred_name": row["preferred_name"],
                "date_of_birth": row["date_of_birth_value"],
                "gender": row["gender"].lower(),
                "admission_date": row["admission_date_value"],
                "status": Learner.Status.ACTIVE,
                "notes": "",
            },
            creation_token=token,
        )
        enrollment = AnnualEnrollment(
            learner=learner,
            academic_year=academic_year,
            learning_group=row["learning_group"],
            enrolled_on=row["admission_date_value"] or timezone.localdate(),
        )
        enrollment.full_clean()
        enrollment.save()
        guardian = _find_or_create_guardian(locked.school, row)
        if guardian:
            link = GuardianLink(
                learner=learner,
                guardian=guardian,
                relationship=row["guardian_relationship"],
                is_primary=not learner.guardian_links.exists(),
            )
            link.full_clean()
            link.save()

    locked.status = ImportBatch.Status.COMMITTED
    locked.rows_imported = len(preview.rows)
    locked.committed_at = timezone.now()
    locked.save(update_fields=["status", "rows_imported", "committed_at"])
    batch.status = locked.status
    batch.rows_imported = locked.rows_imported
    batch.committed_at = locked.committed_at
    return locked.rows_imported
