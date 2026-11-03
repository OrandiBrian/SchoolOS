from datetime import date
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from .tests import FoundationTestMixin
from .models import (AnnualEnrollment, AttendanceRegister, AttendanceEntry, AttendanceChange,
                     SchoolMembership, TeacherClassAssignment)


class AttendanceTests(FoundationTestMixin, TestCase):
    def setUp(self):
        self.clock = patch('core.attendance.timezone.localdate', return_value=date(2027, 2, 4))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.school = self.create_school()
        self.year, self.grade, self.group = self.create_year_structure(self.school)
        self.head, self.head_membership = self.create_member(self.school, 'attendance.head', 'head')
        self.teacher, self.teacher_membership = self.create_member(self.school, 'attendance.teacher', 'teacher')
        TeacherClassAssignment.objects.create(membership=self.teacher_membership, learning_group=self.group)
        self.learner = self.create_learner_record(self.school)
        self.enrolment = AnnualEnrollment.objects.create(learner=self.learner, academic_year=self.year, learning_group=self.group, enrolled_on=date(2027, 1, 4))
        self.url = reverse('attendance_register', args=[self.group.pk, '2027-02-04'])
        self.enter_school(self.client, self.teacher, self.school)

    def post(self, status='', version=0, action='draft', **extra):
        return self.client.post(self.url, {'version': version, f'mark_{self.learner.pk}': status, 'action':action, **extra})

    def test_get_is_read_only_and_unmarked_is_not_present(self):
        self.assertContains(self.client.get(self.url), 'Unmarked')
        self.assertFalse(AttendanceRegister.objects.exists())
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(AttendanceEntry.objects.get().status, '')
        self.assertFalse(AttendanceRegister.objects.get().submitted)

    def test_submission_requires_complete_register_and_records_actor(self):
        self.assertContains(self.post(action='submit'), 'Mark every learner')
        self.assertFalse(AttendanceRegister.objects.exists())
        self.assertEqual(self.post('late', action='submit').status_code, 302)
        register = AttendanceRegister.objects.get()
        self.assertTrue(register.submitted)
        self.assertEqual(register.changes.get().actor, self.teacher)
        self.assertEqual(register.changes.get().changes[0]['after'], 'late')

    def test_teacher_cannot_correct_submitted_register(self):
        self.post('present', action='submit')
        self.assertEqual(self.post('absent', version=1, action='correct', reason='Wrong mark').status_code, 403)
        self.assertEqual(AttendanceEntry.objects.get().status, 'present')

    def test_head_correction_requires_reason_and_preserves_history(self):
        self.post('present', action='submit')
        self.enter_school(self.client, self.head, self.school)
        self.assertContains(self.post('absent', version=1, action='correct'), 'requires a reason')
        self.assertEqual(self.post('absent', version=1, action='correct', reason='Confirmed absent by teacher').status_code, 302)
        self.assertEqual(AttendanceChange.objects.count(), 2)
        change = AttendanceChange.objects.first()
        self.assertEqual(change.actor, self.head)
        self.assertEqual(change.changes[0]['before'], 'present')
        self.assertEqual(change.changes[0]['after'], 'absent')

    def test_stale_write_does_not_overwrite_or_duplicate_audit(self):
        self.post('present')
        response = self.post('absent')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AttendanceEntry.objects.get().status, 'present')
        self.assertEqual(AttendanceChange.objects.count(), 1)

    def test_cross_school_and_unassigned_classes_are_inaccessible(self):
        other = self.create_school('Beta')
        _, _, other_group = self.create_year_structure(other)
        url = reverse('attendance_register', args=[other_group.pk, '2027-02-04'])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'version':0, 'action':'draft'}).status_code, 404)
        self.teacher_membership.teacher_class_assignments.all().delete()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.post('present').status_code, 404)

    def test_forged_learner_status_or_action_cannot_write(self):
        self.assertEqual(self.post('bad-value').status_code, 200)
        self.assertEqual(self.post('present', action='delete').status_code, 200)
        self.assertEqual(self.post('present', mark_99999='present').status_code, 200)
        self.assertFalse(AttendanceRegister.objects.exists())

    def test_future_and_out_of_year_dates_cannot_write(self):
        for day in ['2027-02-05', '2026-12-01']:
            response = self.client.post(reverse('attendance_register', args=[self.group.pk, day]), {'version':0,'action':'draft'})
            self.assertEqual(response.status_code, 403)
        self.assertFalse(AttendanceRegister.objects.exists())

    def test_secretary_read_only_and_board_aggregate_only(self):
        self.post('absent', action='submit')
        secretary, _ = self.create_member(self.school, 'attendance.secretary', 'secretary')
        self.enter_school(self.client, secretary, self.school)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.post('present', version=1).status_code, 403)
        board, _ = self.create_member(self.school, 'attendance.board', 'board')
        self.enter_school(self.client, board, self.school)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        overview = self.client.get(reverse('attendance_overview')+'?date=2027-02-04')
        self.assertEqual(overview.status_code, 200)
        self.assertNotContains(overview, self.learner.full_name)
        self.assertEqual(overview.context['totals']['absent'], 1)

    def test_roster_snapshot_survives_enrolment_changes(self):
        self.post('present')
        self.enrolment.withdrawn_on = date(2027, 2, 3)
        self.enrolment.status = 'withdrawn'
        self.enrolment.save()
        self.assertContains(self.client.get(self.url), self.learner.full_name)
        self.assertEqual(self.post('absent', version=1, action='submit').status_code, 302)

    def test_new_register_excludes_future_joiners_and_withdrawn(self):
        self.enrolment.enrolled_on = date(2027, 2, 5)
        self.enrolment.save()
        self.assertContains(self.client.get(self.url), 'No eligible learners')
        self.enrolment.enrolled_on = date(2027, 1, 4)
        self.enrolment.withdrawn_on = date(2027, 2, 4)
        self.enrolment.save()
        self.assertContains(self.client.get(self.url), 'No eligible learners')

    def test_missing_register_is_not_absence_and_revoked_membership_is_denied(self):
        response = self.client.get(reverse('attendance_overview')+'?date=2027-02-04')
        self.assertEqual(response.context['totals']['missing'], 1)
        self.assertEqual(response.context['totals']['unmarked'], 1)
        self.assertEqual(response.context['totals']['absent'], 0)
        self.teacher_membership.active = False
        self.teacher_membership.save()
        self.assertEqual(self.post('present').status_code, 302)
        self.assertFalse(AttendanceRegister.objects.exists())

    def test_csrf_is_required_for_attendance_mutations(self):
        client = Client(enforce_csrf_checks=True)
        self.enter_school(client, self.teacher, self.school)
        self.assertEqual(client.post(self.url, {'version':0, 'action':'draft'}).status_code, 403)
