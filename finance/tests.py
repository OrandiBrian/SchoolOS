import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from core.tests import FoundationTestMixin
from core.models import AnnualEnrollment, Term
from . import services as ledger
from .models import (FeeSchedule, Invoice, Payment, Allocation, Approval, Adjustment,
                     FinanceEvent, InstalmentPlan, SchoolCounter)

D=Decimal


class FinanceTests(FoundationTestMixin,TestCase):
    def setUp(self):
        self.clock=patch('finance.services.timezone.localdate',return_value=date(2027,2,15))
        self.clock.start();self.addCleanup(self.clock.stop)
        self.school=self.create_school()
        self.year,self.grade,self.group=self.create_year_structure(self.school)
        self.term=Term.objects.create(academic_year=self.year,name='Term 1',starts_on=date(2027,1,4),ends_on=date(2027,3,31))
        self.head,self.hm=self.create_member(self.school,'finance.head','head')
        self.secretary,self.sm=self.create_member(self.school,'finance.secretary','secretary')
        self.learner=self.create_learner_record(self.school)
        AnnualEnrollment.objects.create(learner=self.learner,academic_year=self.year,learning_group=self.group,enrolled_on=date(2027,1,4))
        self.schedule=ledger.save_schedule(self.hm,self.term,self.grade,D('10000'),D('2000'))
        self.enter_school(self.client,self.secretary,self.school)

    def invoice(self,learner=None,token=None,transport=False):
        return ledger.issue_invoice(self.sm,learner or self.learner,self.schedule,date(2027,1,10),transport,token or uuid.uuid4())

    def payment(self,amount='4000',invoice=None,allocation_amount=None,reference='',method='cash',token=None):
        return ledger.record_payment(self.sm,self.learner,'Fictional Parent',method,reference,D(amount),date(2027,1,5),token or uuid.uuid4(),invoice,allocation_amount)

    def request(self,kind='discount',**kw):
        return ledger.request_approval(self.sm,kind,'Verified source record',date(2027,1,1),uuid.uuid4(),**kw)

    def approve(self,request):
        return ledger.review_request(self.hm,request,'approve','Checked against source file')

    def test_invoice_snapshots_and_one_invoice_per_term(self):
        token=uuid.uuid4()
        invoice=self.invoice(token=token,transport=True)
        self.assertEqual(invoice.gross,D('12000'))
        ledger.save_schedule(self.hm,self.term,self.grade,D('20000'),D('3000'))
        invoice.refresh_from_db()
        self.assertEqual(invoice.gross,D('12000'))
        self.assertEqual(self.invoice(token=token).pk,invoice.pk)
        with self.assertRaises(ValidationError):self.invoice()
        self.assertEqual(Invoice.objects.count(),1)

    def test_exact_decimal_payment_and_unallocated_credit(self):
        invoice=self.invoice()
        payment=self.payment('10500.25',invoice,D('10000'))
        self.assertEqual(invoice.outstanding,D('0'))
        self.assertEqual(payment.credit,D('500.25'))
        self.assertEqual(ledger.learner_balances(self.learner)['balance'],D('-500.25'))

    def test_invalid_allocation_rolls_back_entire_payment_and_counter(self):
        invoice=self.invoice()
        with self.assertRaises(ValidationError):self.payment('100',invoice,D('200'))
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(SchoolCounter.objects.get().next_receipt,1)

    def test_reference_normalization_and_replay(self):
        token=uuid.uuid4()
        payment=self.payment(method='mpesa',reference=' abc123 ',token=token)
        self.assertEqual(payment.reference,'ABC123')
        self.assertEqual(self.payment(method='mpesa',reference='abc123',token=token).pk,payment.pk)
        with self.assertRaises(ValidationError):self.payment(method='mpesa',reference='AbC123')
        with self.assertRaises(ValidationError):self.payment(method='bank')
        self.assertEqual(Payment.objects.count(),1)

    def test_sibling_allocation_counts_money_once(self):
        invoice=self.invoice()
        sibling=self.create_learner_record(self.school,'Sibling','Learner')
        AnnualEnrollment.objects.create(learner=sibling,academic_year=self.year,learning_group=self.group)
        second=self.invoice(sibling)
        payment=self.payment('15000',invoice,D('10000'))
        token=uuid.uuid4()
        ledger.allocate(self.sm,payment,second,D('4000'),'Parent requested sibling allocation',token)
        ledger.allocate(self.sm,payment,second,D('4000'),'Parent requested sibling allocation',token)
        self.assertEqual(Allocation.objects.count(),2)
        self.assertEqual(payment.credit,D('1000'))
        self.assertEqual(ledger.learner_balances(self.learner)['balance'],D('-1000'))
        self.assertEqual(ledger.learner_balances(sibling)['balance'],D('6000'))
        self.assertEqual(sum((ledger.learner_balances(l)['balance'] for l in [self.learner,sibling])),D('5000'))

    def test_payment_reversal_restores_debt_and_preserves_history(self):
        invoice=self.invoice()
        payment=self.payment('12000',invoice,D('10000'),method='bank',reference='bank-one')
        request=self.request('payment_reversal',payment=payment)
        self.approve(request)
        payment.refresh_from_db()
        self.assertTrue(payment.reversed)
        self.assertEqual(payment.credit,D('0'))
        self.assertEqual(invoice.outstanding,D('10000'))
        self.assertEqual(Allocation.objects.count(),1)
        with self.assertRaises(ValidationError):ledger.allocate(self.sm,payment,invoice,D('10'),'Try again',uuid.uuid4())
        with self.assertRaises(ValidationError):self.payment(method='bank',reference='bank-one')

    def test_secretary_cannot_approve_and_pending_assistance_does_not_change_balance(self):
        invoice=self.invoice()
        request=self.request(invoice=invoice,amount=D('500'))
        self.assertEqual(invoice.outstanding,D('10000'))
        with self.assertRaises(PermissionDenied):ledger.review_request(self.sm,request,'approve','Trying')
        self.approve(request)
        self.assertEqual(invoice.outstanding,D('9500'))
        with self.assertRaises(ValidationError):self.approve(request)
        self.assertEqual(Adjustment.objects.count(),1)

    def test_stale_assistance_request_revalidates_at_approval(self):
        invoice=self.invoice()
        request=self.request(invoice=invoice,amount=D('9000'))
        self.payment('5000',invoice,D('5000'))
        with self.assertRaises(ValidationError):self.approve(request)
        request.refresh_from_db()
        self.assertEqual(request.status,'pending')
        self.assertFalse(Adjustment.objects.exists())

    def test_assistance_reversal_restores_charge(self):
        invoice=self.invoice()
        self.approve(self.request('bursary',invoice=invoice,amount=D('1000')))
        adjustment=Adjustment.objects.get()
        self.approve(self.request('adjustment_reversal',adjustment=adjustment))
        self.assertEqual(invoice.net,D('10000'))
        adjustment.refresh_from_db()
        self.assertTrue(adjustment.reversed)

    def test_rejected_request_has_no_financial_effect(self):
        invoice=self.invoice()
        request=self.request(invoice=invoice,amount=D('3000'))
        ledger.review_request(self.hm,request,'reject','Not authorized by school')
        self.assertEqual(invoice.outstanding,D('10000'))
        request.refresh_from_db()
        self.assertEqual(request.status,'rejected')

    def test_opening_balances_require_approval_and_credit_is_not_collection(self):
        debit=self.request('opening_debit',learner=self.learner,amount=D('3000'))
        credit=self.request('opening_credit',learner=self.learner,amount=D('1000'))
        self.assertEqual(ledger.learner_balances(self.learner)['balance'],D('0'))
        self.approve(debit);self.approve(credit)
        self.assertEqual(ledger.learner_balances(self.learner)['balance'],D('2000'))
        response=self.client.get(reverse('finance_dashboard'))
        self.assertEqual(response.context['collections'],D('0'))
        self.assertEqual(response.context['net_balance'],D('2000'))

    def test_instalments_are_not_charges_and_track_overdue(self):
        invoice=self.invoice()
        self.payment('3000',invoice,D('3000'))
        ledger.agree_instalments(self.sm,invoice,'Parent','Individual agreement',[(date(2027,1,10),D('5000')),(date(2027,3,10),D('5000'))],uuid.uuid4())
        status=ledger.instalment_status(invoice)
        self.assertEqual(status['overdue'],D('2000'))
        self.assertEqual(invoice.outstanding,D('7000'))
        self.assertFalse(status['needs_revision'])
        self.approve(self.request(invoice=invoice,amount=D('1000')))
        self.assertTrue(ledger.instalment_status(invoice)['needs_revision'])

    def test_invalid_instalment_total_and_duplicate_dates(self):
        invoice=self.invoice()
        for rows in [[(date(2027,1,10),D('5000'))],[(date(2027,1,10),D('5000')),(date(2027,1,10),D('5000'))]]:
            with self.assertRaises(ValidationError):ledger.agree_instalments(self.sm,invoice,'Parent','',rows,uuid.uuid4())
        self.assertFalse(InstalmentPlan.objects.exists())

    def test_amount_precision_and_future_payment_rejected(self):
        for amount in ['-1','0','0.001','NaN','Infinity']:
            with self.assertRaises(ValidationError):self.payment(amount)
        with self.assertRaises(ValidationError):ledger.record_payment(self.sm,self.learner,'Parent','cash','',D('100'),date(2027,2,16),uuid.uuid4())
        self.assertFalse(Payment.objects.exists())

    def test_wrong_grade_schedule_rejected(self):
        from core.models import Grade
        other_grade=Grade.objects.create(school=self.school,name='Grade 2',code='G2')
        schedule=ledger.save_schedule(self.hm,self.term,other_grade,D('100'),D('0'))
        with self.assertRaises(ValidationError):ledger.issue_invoice(self.sm,self.learner,schedule,date(2027,1,10),False,uuid.uuid4())

    def test_cross_school_service_and_form_target_rejected(self):
        other=self.create_school('Beta')
        foreign=self.create_learner_record(other,'Private','Learner')
        with self.assertRaises(PermissionDenied):ledger.record_payment(self.sm,foreign,'Parent','cash','',D('100'),date(2027,1,4),uuid.uuid4())
        response=self.client.post(reverse('finance_payment_create'),{'token':uuid.uuid4(),'credit_owner':foreign.pk,'payer':'Parent','method':'cash','amount':'100','received_on':'2027-01-04'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.client.get(reverse('finance_statement',args=[foreign.pk])).status_code,404)

    def test_cross_school_invoice_and_receipt_are_hidden(self):
        invoice=self.invoice();payment=self.payment()
        other=self.create_school('Beta')
        other_head,_=self.create_member(other,'foreign.head','head')
        self.enter_school(self.client,other_head,other)
        for route,pk in [('finance_invoice',invoice.pk),('finance_receipt',payment.pk)]:
            self.assertEqual(self.client.get(reverse(route,args=[pk])).status_code,404)
        response=self.client.get(reverse('finance_dashboard'))
        self.assertNotContains(response,self.learner.full_name)
        self.assertEqual(response.context['collections'],D('0'))

    def test_director_board_summary_only_teacher_denied(self):
        invoice=self.invoice();payment=self.payment()
        for role in ['director','board','teacher']:
            user,_=self.create_member(self.school,'finance.'+role,role)
            self.enter_school(self.client,user,self.school)
            response=self.client.get(reverse('finance_dashboard'))
            self.assertEqual(response.status_code,403 if role=='teacher' else 200)
            if response.status_code==200:self.assertNotContains(response,self.learner.full_name)
            for route in ['finance_payment_create','finance_approval_create','finance_audit','finance_schedule']:
                self.assertEqual(self.client.get(reverse(route)).status_code,403)
            self.assertEqual(self.client.get(reverse('finance_receipt',args=[payment.pk])).status_code,403)
            self.assertEqual(self.client.get(reverse('finance_invoice',args=[invoice.pk])).status_code,403)

    def test_revoked_membership_cannot_write(self):
        self.sm.active=False;self.sm.save()
        with self.assertRaises(PermissionDenied):self.payment()
        self.assertFalse(Payment.objects.exists())

    def test_views_render_and_end_to_end_payment_post_is_idempotent(self):
        invoice=self.invoice()
        payload={'token':str(uuid.uuid4()),'credit_owner':self.learner.pk,'payer':'Parent','method':'mpesa','reference':'TEST999','amount':'2500','received_on':'2027-01-04','invoice':invoice.pk,'allocation_amount':'2500'}
        for _ in range(2):self.assertEqual(self.client.post(reverse('finance_payment_create'),payload).status_code,302)
        self.assertEqual(Payment.objects.count(),1)
        self.assertEqual(invoice.outstanding,D('7500'))
        routes=[('finance_invoice',[invoice.pk]),('finance_receipt',[Payment.objects.get().pk]),('finance_statement',[self.learner.pk]),('finance_payments',[]),('finance_audit',[]),('finance_approvals',[]),('finance_dashboard',[]),('finance_plan',[invoice.pk])]
        for route,args in routes:self.assertEqual(self.client.get(reverse(route,args=args)).status_code,200)

    def test_approval_form_and_review_permissions(self):
        invoice=self.invoice()
        payload={'token':str(uuid.uuid4()),'kind':'discount','invoice':invoice.pk,'amount':'100','effective_date':'2027-01-05','reason':'Verified discount'}
        self.assertEqual(self.client.post(reverse('finance_approval_create'),payload).status_code,302)
        request=Approval.objects.get()
        url=reverse('finance_review',args=[request.pk])
        self.assertEqual(self.client.post(url,{'decision':'approve','note':'Checked'}).status_code,403)
        self.enter_school(self.client,self.head,self.school)
        self.assertEqual(self.client.post(url,{'decision':'approve','note':'Checked'}).status_code,302)
        self.assertEqual(invoice.outstanding,D('9900'))
        self.assertEqual(self.client.get(url).status_code,200)

    def test_financial_post_requires_csrf(self):
        client=Client(enforce_csrf_checks=True)
        self.enter_school(client,self.secretary,self.school)
        self.assertEqual(client.post(reverse('finance_payment_create'),{}).status_code,403)

    def test_reversal_target_and_amount_cannot_be_confused(self):
        invoice=self.invoice();payment=self.payment()
        for kw in [{'invoice':invoice,'payment':payment}, {'payment':payment,'amount':D('10')}]:
            with self.assertRaises(ValidationError):self.request('payment_reversal',**kw)
        self.assertFalse(Approval.objects.exists())

    def test_approval_creation_replay_does_not_duplicate_requests(self):
        token=uuid.uuid4();invoice=self.invoice()
        first=ledger.request_approval(self.sm,'discount','Reason',date(2027,1,1),token,invoice=invoice,amount=D('50'))
        second=ledger.request_approval(self.sm,'discount','Reason',date(2027,1,1),token,invoice=invoice,amount=D('50'))
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(Approval.objects.count(),1)

    def test_invoice_reversal_releases_allocations_and_allows_corrected_reissue(self):
        invoice=self.invoice()
        payment=self.payment('5000',invoice,D('5000'))
        self.approve(self.request('invoice_reversal',invoice=invoice))
        invoice.refresh_from_db()
        self.assertTrue(invoice.voided)
        self.assertEqual(invoice.outstanding,D('0'))
        self.assertEqual(payment.credit,D('5000'))
        self.assertEqual(Allocation.objects.count(),1)
        replacement=self.invoice()
        self.assertNotEqual(invoice.number,replacement.number)
        ledger.allocate(self.sm,payment,replacement,D('5000'),'Corrected invoice',uuid.uuid4())
        self.assertEqual(payment.credit,D('0'))
        self.assertEqual(ledger.learner_balances(self.learner)['balance'],D('5000'))
        self.assertEqual(self.client.get(reverse('finance_statement',args=[self.learner.pk])).status_code,200)
        with self.assertRaises(ValidationError):ledger.allocate(self.sm,payment,invoice,D('1'),'Invalid',uuid.uuid4())

    def test_disabled_user_cannot_execute_financial_service(self):
        self.secretary.is_active=False
        self.secretary.save(update_fields=['is_active'])
        with self.assertRaises(PermissionDenied):self.payment()
        self.assertFalse(Payment.objects.exists())

    def test_finance_demo_is_explicit_idempotent_and_fictional(self):
        from django.core.management import call_command
        from django.test import override_settings
        import io
        with override_settings(DEBUG=True):
            call_command('seed_demo',password='demo-password-123',stdout=io.StringIO())
            call_command('seed_finance_demo',stdout=io.StringIO())
            counts=(Invoice.objects.count(),Payment.objects.count(),Approval.objects.count(),InstalmentPlan.objects.count())
            call_command('seed_finance_demo',stdout=io.StringIO())
            self.assertEqual(counts,(Invoice.objects.count(),Payment.objects.count(),Approval.objects.count(),InstalmentPlan.objects.count()))
        with override_settings(DEBUG=False):
            from django.core.management.base import CommandError
            with self.assertRaises(CommandError):call_command('seed_finance_demo',stdout=io.StringIO())


# Run this against the actual PostgreSQL backend before live use.
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import connection, close_old_connections
from django.test import TransactionTestCase

@unittest.skipUnless(connection.vendor=='postgresql','Financial row-lock concurrency requires PostgreSQL.')
class FinanceConcurrencyTests(FoundationTestMixin,TransactionTestCase):
    def test_parallel_allocations_cannot_overspend_credit(self):
        school=self.create_school('Lock')
        year,grade,group=self.create_year_structure(school)
        term=Term.objects.create(academic_year=year,name='Term 1',starts_on=date(2027,1,4),ends_on=date(2027,3,31))
        user,member=self.create_member(school,'lock.head','head')
        learner=self.create_learner_record(school)
        AnnualEnrollment.objects.create(learner=learner,academic_year=year,learning_group=group)
        schedule=ledger.save_schedule(member,term,grade,D('1000'),D('0'))
        invoice=ledger.issue_invoice(member,learner,schedule,date(2027,1,10),False,uuid.uuid4())
        payment=ledger.record_payment(member,learner,'Parent','cash','',D('100'),date(2026,1,1),uuid.uuid4())
        barrier=Barrier(2)
        def worker(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    ledger.allocate(member,payment,invoice,D('100'),'Concurrent test',uuid.uuid4())
                    return 'saved'
                except ValidationError:return 'rejected'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(worker,[1,2]))
        self.assertEqual(sorted(outcomes),['rejected','saved'])
        self.assertEqual(payment.credit,D('0'))
        self.assertEqual(invoice.paid,D('100'))
