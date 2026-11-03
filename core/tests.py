import csv
import io
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

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
    SchoolMembership,
    StaffRecord,
    TeacherClassAssignment,
)
from .services import CSV_HEADERS, create_learner


class FoundationTestMixin:
    password = "test-password-123"

    def create_school(self, label="Alpha"):
        return School.objects.create(
            name=f"{label} School",
            admission_prefix=label[:1].upper() * 2,
        )

    def create_user(self, username):
        return get_user_model().objects.create_user(
            username=username, password=self.password
        )

    def create_member(self, school, username, role, staff_record=None):
        user = self.create_user(username)
        membership = SchoolMembership.objects.create(
            school=school,
            user=user,
            role=role,
            staff_record=staff_record,
        )
        return user, membership

    def enter_school(self, client, user, school):
        client.force_login(user)
        session = client.session
        session["active_school_id"] = school.pk
        session.save()

    def create_year_structure(
        self, school, year_name="2027", grade_name="PP1", teacher_group_name="A"
    ):
        year = AcademicYear.objects.create(
            school=school,
            name=year_name,
            starts_on=date(int(year_name), 1, 3),
            ends_on=date(int(year_name), 11, 30),
            is_current=True,
        )
        grade = Grade.objects.create(
            school=school,
            name=grade_name,
            code=grade_name.replace(" ", ""),
            sort_order=1,
        )
        group = LearningGroup.objects.create(
            academic_year=year,
            grade=grade,
            name=teacher_group_name,
            capacity=30,
        )
        return year, grade, group

    def learner_payload(self, first_name="Amina", last_name="Otieno"):
        return {
            "first_name": first_name,
            "middle_name": "",
            "last_name": last_name,
            "preferred_name": "",
            "date_of_birth": "2018-04-12",
            "gender": "female",
            "admission_date": "2027-01-04",
            "status": "active",
            "notes": "",
            "submission_token": str(uuid.uuid4()),
            "duplicate_reviewed": "",
        }

    def create_learner_record(self, school, first_name="Amina", last_name="Otieno"):
        learner, _ = create_learner(
            school,
            None,
            {
                "first_name": first_name,
                "middle_name": "",
                "last_name": last_name,
                "preferred_name": "",
                "date_of_birth": date(2018, 4, 12),
                "gender": Learner.Gender.FEMALE,
                "admission_date": date(2027, 1, 4),
                "status": Learner.Status.ACTIVE,
                "notes": "",
            },
            creation_token=uuid.uuid4(),
        )
        return learner

    def import_csv(self, rows):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()

    def default_import_row(self, first_name="Sanaa", last_name="Achieng"):
        return {
            "first_name": first_name,
            "middle_name": "",
            "last_name": last_name,
            "preferred_name": "",
            "date_of_birth": "2018-10-09",
            "gender": "female",
            "admission_date": "2027-01-04",
            "grade": "PP1",
            "stream": "A",
            "guardian_first_name": "Zuri",
            "guardian_last_name": "Hassan",
            "guardian_relationship": "Guardian",
            "guardian_phone": "+254700555001",
            "guardian_email": "zuri@example.test",
        }


class TenancyIsolationTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.alpha = self.create_school("Alpha")
        self.bravo = self.create_school("Bravo")
        self.alpha_year, self.alpha_grade, self.alpha_group = (
            self.create_year_structure(self.alpha)
        )
        self.bravo_year, self.bravo_grade, self.bravo_group = (
            self.create_year_structure(self.bravo)
        )
        self.alpha_head, self.alpha_membership = self.create_member(
            self.alpha, "alpha-head", SchoolMembership.Role.HEAD
        )
        self.bravo_head, _ = self.create_member(
            self.bravo, "bravo-head", SchoolMembership.Role.HEAD
        )
        self.alpha_learner = self.create_learner_record(
            self.alpha, "Alpha", "Learner"
        )
        self.bravo_learner = self.create_learner_record(
            self.bravo, "Bravo", "Learner"
        )
        AnnualEnrollment.objects.create(
            learner=self.alpha_learner,
            academic_year=self.alpha_year,
            learning_group=self.alpha_group,
        )
        AnnualEnrollment.objects.create(
            learner=self.bravo_learner,
            academic_year=self.bravo_year,
            learning_group=self.bravo_group,
        )
        self.client = Client()
        self.enter_school(self.client, self.alpha_head, self.alpha)

    def test_list_and_detail_are_school_scoped(self):
        response = self.client.get(reverse("learner_list"))
        self.assertContains(response, self.alpha_learner.full_name)
        self.assertNotContains(response, self.bravo_learner.full_name)
        self.assertEqual(
            self.client.get(
                reverse("learner_detail", args=[self.bravo_learner.pk])
            ).status_code,
            404,
        )

    def test_cross_school_edit_get_and_post_are_rejected(self):
        url = reverse("learner_edit", args=[self.bravo_learner.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post(
            url,
            {
                **self.learner_payload("Changed", "Name"),
                "school": self.alpha.pk,
            },
        )
        self.assertEqual(response.status_code, 404)
        self.bravo_learner.refresh_from_db()
        self.assertEqual(self.bravo_learner.first_name, "Bravo")

    def test_posted_school_id_does_not_escape_active_membership(self):
        response = self.client.post(
            reverse("learner_create"),
            {**self.learner_payload("Scoped", "Learner"), "school": self.bravo.pk},
        )
        self.assertEqual(response.status_code, 302)
        created = Learner.objects.get(first_name="Scoped", last_name="Learner")
        self.assertEqual(created.school, self.alpha)
        self.assertFalse(
            Learner.objects.filter(
                school=self.bravo, first_name="Scoped", last_name="Learner"
            ).exists()
        )

    def test_foreign_guardian_post_returns_validation_error(self):
        foreign_guardian = Guardian.objects.create(
            school=self.bravo, first_name="Foreign", last_name="Guardian"
        )
        response = self.client.post(
            reverse("guardian_add", args=[self.alpha_learner.pk]),
            {
                "guardian": foreign_guardian.pk,
                "relationship": "Aunt",
                "is_primary": "on",
                "can_receive_school_communications": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            GuardianLink.objects.filter(
                learner=self.alpha_learner, guardian=foreign_guardian
            ).exists()
        )

    def test_foreign_year_and_group_post_is_rejected(self):
        response = self.client.post(
            reverse("enrollment_add", args=[self.alpha_learner.pk]),
            {
                "academic_year": self.bravo_year.pk,
                "learning_group": self.bravo_group.pk,
                "status": AnnualEnrollment.Status.ACTIVE,
                "enrolled_on": "2027-01-05",
                "withdrawn_on": "",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AnnualEnrollment.objects.filter(
                learner=self.alpha_learner, academic_year=self.bravo_year
            ).exists()
        )

    def test_school_settings_never_mutate_other_school(self):
        response = self.client.post(
            reverse("school_settings"),
            {
                "name": "Alpha Updated",
                "admission_prefix": "AA",
                "motto": "",
                "address": "",
                "phone": "",
                "email": "",
                "school": self.bravo.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.alpha.refresh_from_db()
        self.bravo.refresh_from_db()
        self.assertEqual(self.alpha.name, "Alpha Updated")
        self.assertEqual(self.bravo.name, "Bravo School")

    def test_cross_school_import_batch_lookup_is_rejected(self):
        batch = ImportBatch.objects.create(
            school=self.bravo,
            academic_year=self.bravo_year,
            original_filename="other.csv",
            csv_text=self.import_csv([]),
            created_by=self.bravo_head,
        )
        response = self.client.get(
            reverse("import_preview", args=[batch.token])
        )
        self.assertEqual(response.status_code, 404)


class RoleAuthorizationTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.school = self.create_school("Alpha")
        self.year, self.grade, self.assigned_group = self.create_year_structure(
            self.school
        )
        other_grade = Grade.objects.create(
            school=self.school, name="PP2", code="PP2", sort_order=2
        )
        self.unassigned_group = LearningGroup.objects.create(
            academic_year=self.year, grade=other_grade, name="A"
        )
        self.head, _ = self.create_member(
            self.school, "head", SchoolMembership.Role.HEAD
        )
        self.secretary, _ = self.create_member(
            self.school, "secretary", SchoolMembership.Role.SECRETARY
        )
        self.teacher, self.teacher_membership = self.create_member(
            self.school, "teacher", SchoolMembership.Role.TEACHER
        )
        TeacherClassAssignment.objects.create(
            membership=self.teacher_membership,
            learning_group=self.assigned_group,
        )
        self.director, _ = self.create_member(
            self.school, "director", SchoolMembership.Role.DIRECTOR
        )
        self.board, _ = self.create_member(
            self.school, "board", SchoolMembership.Role.BOARD
        )
        self.visible = self.create_learner_record(self.school, "Visible", "Learner")
        self.hidden = self.create_learner_record(self.school, "Hidden", "Learner")
        AnnualEnrollment.objects.create(
            learner=self.visible,
            academic_year=self.year,
            learning_group=self.assigned_group,
        )
        AnnualEnrollment.objects.create(
            learner=self.hidden,
            academic_year=self.year,
            learning_group=self.unassigned_group,
        )
        self.client = Client()

    def test_secretary_can_manage_registration(self):
        self.enter_school(self.client, self.secretary, self.school)
        self.assertEqual(
            self.client.get(reverse("learner_create")).status_code, 200
        )
        response = self.client.post(
            reverse("learner_create"),
            self.learner_payload("Secretary", "Created"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Learner.objects.filter(
                school=self.school,
                first_name="Secretary",
                last_name="Created",
            ).exists()
        )

    def test_teacher_sees_only_assigned_class_and_cannot_write(self):
        self.enter_school(self.client, self.teacher, self.school)
        response = self.client.get(reverse("learner_list"))
        self.assertContains(response, self.visible.full_name)
        self.assertNotContains(response, self.hidden.full_name)
        self.assertEqual(
            self.client.get(
                reverse("learner_detail", args=[self.hidden.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("learner_create")).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("learner_edit", args=[self.visible.pk]),
                self.learner_payload("Teacher", "Write"),
            ).status_code,
            403,
        )

    def test_director_and_board_receive_summary_without_people_pages(self):
        for user in [self.director, self.board]:
            self.enter_school(self.client, user, self.school)
            response = self.client.get(reverse("dashboard"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Aggregate view")
            self.assertNotContains(response, self.visible.full_name)
            self.assertEqual(
                self.client.get(reverse("learner_list")).status_code, 403
            )

    def test_staff_management_is_head_only(self):
        self.enter_school(self.client, self.secretary, self.school)
        self.assertEqual(self.client.get(reverse("staff_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("staff_create")).status_code, 403)
        self.enter_school(self.client, self.head, self.school)
        self.assertEqual(self.client.get(reverse("staff_list")).status_code, 200)

    def test_non_teaching_staff_record_does_not_create_login(self):
        before = get_user_model().objects.count()
        self.enter_school(self.client, self.head, self.school)
        response = self.client.post(
            reverse("staff_create"),
            {
                "first_name": "Night",
                "middle_name": "",
                "last_name": "Guard",
                "category": StaffRecord.Category.SUPPORT,
                "employee_number": "SUP-1",
                "email": "",
                "phone": "",
                "active": "on",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_user_model().objects.count(), before)
        self.assertTrue(
            StaffRecord.objects.filter(
                school=self.school,
                first_name="Night",
                category=StaffRecord.Category.SUPPORT,
            ).exists()
        )

    def test_board_session_cannot_open_administrative_views(self):
        self.enter_school(self.client, self.board, self.school)
        for name in ["academics", "school_settings", "membership_create"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_csrf_is_required_for_sensitive_post(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.enter_school(csrf_client, self.head, self.school)
        response = csrf_client.post(
            reverse("learner_create"),
            self.learner_payload("Missing", "Csrf"),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Learner.objects.filter(
                school=self.school, first_name="Missing", last_name="Csrf"
            ).exists()
        )


class AdmissionNumberTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.school = self.create_school("Alpha")
        self.other_school = self.create_school("Bravo")
        self.head, _ = self.create_member(
            self.school, "head", SchoolMembership.Role.HEAD
        )

    def test_numbers_are_sequential_unique_and_survive_updates(self):
        first = self.create_learner_record(self.school, "First", "Learner")
        second = self.create_learner_record(self.school, "Second", "Learner")
        self.assertRegex(first.admission_number, r"^AA-\d{6}$")
        self.assertEqual(first.admission_number, "AA-000001")
        self.assertEqual(second.admission_number, "AA-000002")
        original = first.admission_number
        first.first_name = "Renamed"
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.admission_number, original)

    def test_database_constraint_rejects_duplicate_number_in_school(self):
        first = self.create_learner_record(self.school, "First", "Learner")
        duplicate = Learner(
            school=self.school,
            admission_number=first.admission_number,
            first_name="Duplicate",
            middle_name="",
            last_name="Number",
            admission_date=date(2027, 1, 4),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_repeated_submission_token_returns_same_learner(self):
        token = uuid.uuid4()
        payload = {
            "first_name": "Repeated",
            "middle_name": "",
            "last_name": "Submission",
            "preferred_name": "",
            "date_of_birth": date(2018, 1, 1),
            "gender": Learner.Gender.FEMALE,
            "admission_date": date(2027, 1, 4),
            "status": Learner.Status.ACTIVE,
            "notes": "",
        }
        first, first_created = create_learner(
            self.school, self.head, payload, creation_token=token
        )
        second, second_created = create_learner(
            self.school, self.head, payload, creation_token=token
        )
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 1)

    def test_duplicate_name_warning_requires_explicit_review(self):
        self.create_learner_record(self.school, "Amina", "Otieno")
        client = Client()
        self.enter_school(client, self.head, self.school)
        payload = self.learner_payload("Amina", "Otieno")
        response = client.post(reverse("learner_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review the possible duplicate")
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 1)
        payload["duplicate_reviewed"] = "on"
        response = client.post(reverse("learner_create"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 2)

    def test_prefix_cannot_change_after_number_issued(self):
        self.create_learner_record(self.school)
        client = Client()
        self.enter_school(client, self.head, self.school)
        response = client.post(
            reverse("school_settings"),
            {
                "name": self.school.name,
                "admission_prefix": "ZZ",
                "motto": "",
                "address": "",
                "phone": "",
                "email": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot change")
        self.school.refresh_from_db()
        self.assertEqual(self.school.admission_prefix, "AA")


class GuardianAndEnrollmentTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.school = self.create_school("Alpha")
        self.other_school = self.create_school("Bravo")
        self.year, self.grade, self.group = self.create_year_structure(self.school)
        self.next_year = AcademicYear.objects.create(
            school=self.school,
            name="2028",
            starts_on=date(2028, 1, 3),
            ends_on=date(2028, 11, 30),
        )
        self.next_group = LearningGroup.objects.create(
            academic_year=self.next_year, grade=self.grade, name="A"
        )
        self.head, _ = self.create_member(
            self.school, "head", SchoolMembership.Role.HEAD
        )
        self.client = Client()
        self.enter_school(self.client, self.head, self.school)
        self.first = self.create_learner_record(self.school, "First", "Sibling")
        self.second = self.create_learner_record(self.school, "Second", "Sibling")
        self.guardian = Guardian.objects.create(
            school=self.school,
            first_name="Shared",
            last_name="Guardian",
            phone="+254700101010",
        )

    def test_shared_guardian_links_multiple_siblings(self):
        GuardianLink.objects.create(
            learner=self.first,
            guardian=self.guardian,
            relationship="Mother",
        )
        GuardianLink.objects.create(
            learner=self.second,
            guardian=self.guardian,
            relationship="Mother",
        )
        self.assertEqual(self.guardian.learner_links.count(), 2)

    def test_guardian_cross_school_link_fails_model_validation(self):
        foreign = Guardian.objects.create(
            school=self.other_school, first_name="Foreign", last_name="Guardian"
        )
        link = GuardianLink(
            learner=self.first, guardian=foreign, relationship="Guardian"
        )
        with self.assertRaisesMessage(Exception, "must belong to the same school"):
            link.full_clean()

    def test_annual_enrollment_is_unique_and_history_is_preserved(self):
        first = AnnualEnrollment.objects.create(
            learner=self.first,
            academic_year=self.year,
            learning_group=self.group,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AnnualEnrollment.objects.create(
                    learner=self.first,
                    academic_year=self.year,
                    learning_group=self.group,
                )
        AnnualEnrollment.objects.create(
            learner=self.first,
            academic_year=self.next_year,
            learning_group=self.next_group,
        )
        self.assertEqual(self.first.enrollments.count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.academic_year, self.year)
        self.assertEqual(first.learning_group, self.group)

    def test_cross_school_year_fails_model_validation(self):
        other_year, _, other_group = self.create_year_structure(
            self.other_school, "2028"
        )
        enrollment = AnnualEnrollment(
            learner=self.first,
            academic_year=other_year,
            learning_group=other_group,
        )
        with self.assertRaisesMessage(Exception, "learner's school"):
            enrollment.full_clean()

    def test_enrollment_view_creates_then_rejects_duplicate(self):
        payload = {
            "academic_year": self.year.pk,
            "learning_group": self.group.pk,
            "status": AnnualEnrollment.Status.ACTIVE,
            "enrolled_on": "2027-01-05",
            "withdrawn_on": "",
            "notes": "",
        }
        response = self.client.post(
            reverse("enrollment_add", args=[self.first.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.first.enrollments.count(), 1)
        response = self.client.post(
            reverse("enrollment_add", args=[self.first.pk]), payload
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.first.enrollments.count(), 1)


class CsvImportTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.school = self.create_school("Alpha")
        self.other_school = self.create_school("Bravo")
        self.year, self.grade, self.group = self.create_year_structure(self.school)
        self.other_year, _, _ = self.create_year_structure(
            self.other_school, "2027"
        )
        self.head, _ = self.create_member(
            self.school, "head", SchoolMembership.Role.HEAD
        )
        self.client = Client()
        self.enter_school(self.client, self.head, self.school)

    def upload(self, rows):
        content = self.import_csv(rows).encode()
        return self.client.post(
            reverse("import_upload"),
            {
                "academic_year": self.year.pk,
                "file": SimpleUploadedFile(
                    "learners.csv", content, content_type="text/csv"
                ),
            },
        )

    def test_preview_does_not_create_records_and_confirmation_is_idempotent(self):
        response = self.upload([self.default_import_row()])
        self.assertEqual(response.status_code, 302)
        batch = ImportBatch.objects.get(school=self.school)
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 0)
        preview = self.client.get(reverse("import_preview", args=[batch.token]))
        self.assertContains(preview, "Validation passed")
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 0)
        confirm_url = reverse("import_preview", args=[batch.token])
        response = self.client.post(confirm_url, {})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 1)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.Status.COMMITTED)
        response = self.client.post(confirm_url, {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 1)

    def test_validation_errors_mean_no_partial_import(self):
        valid = self.default_import_row()
        invalid = self.default_import_row("Broken", "Row")
        invalid["grade"] = "Not a grade"
        self.upload([valid, invalid])
        batch = ImportBatch.objects.get(school=self.school)
        preview = self.client.get(reverse("import_preview", args=[batch.token]))
        self.assertContains(preview, "Validation failed")
        self.assertContains(preview, "No matching class")
        self.client.post(
            reverse("import_preview", args=[batch.token]), {}
        )
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 0)

    def test_possible_duplicate_requires_explicit_confirmation(self):
        existing = self.default_import_row()
        existing_learner = self.create_learner_record(
            self.school, existing["first_name"], existing["last_name"]
        )
        existing_learner.date_of_birth = date(2018, 10, 9)
        existing_learner.save(update_fields=["date_of_birth"])
        self.upload([existing])
        batch = ImportBatch.objects.get(school=self.school)
        url = reverse("import_preview", args=[batch.token])
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Possible duplicates")
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 1)
        response = self.client.post(url, {"confirm_possible_duplicates": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Learner.objects.filter(school=self.school).count(), 2)

    def test_import_uses_only_active_school_classes(self):
        row = self.default_import_row()
        self.upload([row])
        batch = ImportBatch.objects.get(school=self.school)
        self.client.post(reverse("import_preview", args=[batch.token]), {})
        learner = Learner.objects.get(school=self.school)
        enrollment = learner.enrollments.get(academic_year=self.year)
        self.assertEqual(enrollment.learning_group.academic_year.school, self.school)

    def test_template_download_contains_required_headers(self):
        response = self.client.get(reverse("import_template"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn(",".join(CSV_HEADERS), response.content.decode())

    def test_import_does_not_assume_shared_contact_proves_guardian_identity(self):
        first = self.default_import_row("First", "Sibling")
        second = self.default_import_row("Second", "Sibling")
        self.upload([first, second])
        batch = ImportBatch.objects.get(school=self.school)
        self.client.post(reverse("import_preview", args=[batch.token]), {})
        self.assertEqual(Guardian.objects.filter(school=self.school).count(), 2)
        self.assertEqual(GuardianLink.objects.count(), 2)


class AdminBoundaryTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.school = self.create_school("Alpha")
        self.head, _ = self.create_member(
            self.school, "head", SchoolMembership.Role.HEAD
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="superuser",
            email="superuser@example.test",
            password=self.password,
        )

    def test_ordinary_school_head_cannot_open_global_admin(self):
        client = Client()
        self.enter_school(client, self.head, self.school)
        response = client.get(reverse("admin:index"))
        self.assertNotEqual(response.status_code, 200)
        self.assertIn(response.status_code, {302, 403})

    def test_superuser_can_open_global_admin(self):
        client = Client()
        client.force_login(self.superuser)
        response = client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)


@override_settings(DEBUG=True)
class DemoCommandTests(FoundationTestMixin, TestCase):
    def test_demo_command_is_idempotent_and_fictional(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            call_command("seed_demo", password="demo-password-123")
        first_counts = (
            School.objects.count(),
            Learner.objects.count(),
            AcademicYear.objects.count(),
            AnnualEnrollment.objects.count(),
            SchoolMembership.objects.count(),
        )
        with patch("sys.stdout", new_callable=io.StringIO):
            call_command("seed_demo", password="demo-password-123")
        second_counts = (
            School.objects.count(),
            Learner.objects.count(),
            AcademicYear.objects.count(),
            AnnualEnrollment.objects.count(),
            SchoolMembership.objects.count(),
        )
        self.assertEqual(first_counts, second_counts)
        school = School.objects.get()
        self.assertIn("Fictional", school.name)
        self.assertEqual(
            LearningGroup.objects.filter(
                academic_year__name="2027", grade__name="Grade 1"
            ).count(),
            2,
        )
        self.assertFalse(
            get_user_model().objects.filter(username="demo.cook").exists()
        )


@unittest.skipUnless(
    connection.vendor == "postgresql",
    "PostgreSQL row locking concurrency check requires a PostgreSQL test database.",
)
class PostgreSQLAdmissionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_creation_gets_unique_numbers(self):
        school = School.objects.create(name="Concurrent School", admission_prefix="CC")
        barrier = threading.Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                learner, _ = create_learner(
                    school,
                    None,
                    {
                        "first_name": f"Learner{index}",
                        "middle_name": "",
                        "last_name": "Concurrent",
                        "preferred_name": "",
                        "date_of_birth": None,
                        "gender": "",
                        "admission_date": date(2027, 1, 4),
                        "status": Learner.Status.ACTIVE,
                        "notes": "",
                    },
                    creation_token=uuid.uuid4(),
                )
                return learner.admission_number
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            numbers = list(executor.map(worker, [1, 2]))
        self.assertEqual(len(numbers), 2)
        self.assertEqual(len(set(numbers)), 2)
        self.assertEqual(set(numbers), {"CC-000001", "CC-000002"})

class ReviewRegressionTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.school = self.create_school()
        self.year, self.grade, self.group = self.create_year_structure(self.school)
        self.head, _ = self.create_member(self.school, 'review.head', SchoolMembership.Role.HEAD)
        self.enter_school(self.client, self.head, self.school)

    def test_head_cannot_enumerate_or_claim_other_school_accounts(self):
        other = self.create_school('Beta')
        stranger, _ = self.create_member(other, 'private.other.head', SchoolMembership.Role.HEAD)
        response = self.client.get(reverse('membership_create'))
        self.assertNotContains(response, stranger.username)
        response = self.client.post(reverse('membership_create'), {'user': stranger.pk, 'role': 'head'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SchoolMembership.objects.filter(school=self.school, user=stranger).exists())

    def test_head_can_create_school_scoped_account(self):
        response = self.client.post(reverse('membership_create'), {'username': 'new.teacher', 'first_name': 'New', 'last_name': 'Teacher', 'password': 'Unique-test-password-982!', 'role': 'teacher'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SchoolMembership.objects.filter(school=self.school, user__username='new.teacher').exists())

    def test_teacher_assignment_can_be_saved_twice(self):
        _, member = self.create_member(self.school, 'review.teacher', 'teacher')
        for _ in range(2):
            response = self.client.post(reverse('teacher_classes', args=[member.pk]), {'classes': [self.group.pk]})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(member.teacher_class_assignments.count(), 1)

    def test_invalid_duplicate_grade_and_term_render_errors(self):
        response = self.client.post(reverse('grade_create'), {'name': self.grade.name, 'code': self.grade.code, 'sort_order': 1, 'active': 'on'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('term_create', args=[self.year.pk]), {'name':'Bad term', 'starts_on':'2026-01-01', 'ends_on':'2026-03-01', 'sequence':1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.year.terms.count(), 0)

    def test_new_current_year_switches_atomically(self):
        response = self.client.post(reverse('academic_year_create'), {'name':'2028', 'starts_on':'2028-01-01', 'ends_on':'2028-12-01', 'is_current':'on'})
        self.assertEqual(response.status_code, 302)
        self.year.refresh_from_db()
        self.assertFalse(self.year.is_current)

    def test_malformed_date_in_duplicate_search_is_safe(self):
        response = self.client.get(reverse('duplicate_check'), {'first_name':'Amina', 'last_name':'Otieno', 'date_of_birth':'bad-date'})
        self.assertEqual(response.status_code, 200)

    def test_import_preview_rejects_extra_columns_and_bad_email(self):
        from .services import validate_learner_csv
        row = self.default_import_row()
        row['guardian_email'] = 'invalid-email'
        preview = validate_learner_csv(self.school, self.year, self.import_csv([row]))
        self.assertFalse(preview.valid)
        preview = validate_learner_csv(self.school, self.year, self.import_csv([self.default_import_row()]).rstrip() + ',unexpected\n')
        self.assertFalse(preview.valid)

    def test_relink_guardian_returns_form_error(self):
        learner = self.create_learner_record(self.school)
        guardian = Guardian.objects.create(school=self.school, first_name='A', last_name='Parent')
        GuardianLink.objects.create(learner=learner, guardian=guardian, relationship='Parent')
        response = self.client.post(reverse('guardian_add', args=[learner.pk]), {'guardian':guardian.pk, 'relationship':'Parent'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(learner.guardian_links.count(), 1)
