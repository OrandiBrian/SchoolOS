import uuid
from datetime import date
from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from core.models import School, SchoolMembership, AnnualEnrollment, Term
from finance import services
from finance.models import FeeSchedule, Invoice, Approval, Payment, InstalmentPlan


def token(label):return uuid.uuid5(uuid.NAMESPACE_URL,'schoolos-fictional-finance:'+label)


class Command(BaseCommand):
    help='Explicitly add fictional amounts to the existing fictional demo school; idempotent.'

    @transaction.atomic
    def handle(self,*args,**kwargs):
        if not settings.DEBUG:raise CommandError('Demo seeding is disabled outside development.')
        try:
            school=School.objects.get(name='Lofty Creek Demo School (Fictional)')
            member=SchoolMembership.objects.get(school=school,user__username='demo.head',role='head',active=True)
            term=Term.objects.get(academic_year__school=school,academic_year__name='2027',sequence=1)
        except (School.DoesNotExist,SchoolMembership.DoesNotExist,Term.DoesNotExist):
            raise CommandError('Run seed_demo first. This command only targets its exact fictional school.')
        enrolments=AnnualEnrollment.objects.filter(academic_year=term.academic_year).select_related('learner','learning_group__grade').order_by('learner_id')[:3]
        invoices=[]
        for enrolment in enrolments:
            grade=enrolment.learning_group.grade
            schedule=FeeSchedule.objects.filter(school=school,term=term,grade=grade).first()
            if not schedule:schedule=services.save_schedule(member,term,grade,Decimal('15000'),Decimal('3000'))
            invoice=Invoice.objects.filter(school=school,learner=enrolment.learner,term=term,voided=False).first()
            if not invoice:invoice=services.issue_invoice(member,enrolment.learner,schedule,date(2027,1,15),True,token(f'invoice-{enrolment.learner_id}'))
            invoices.append(invoice)
        if not invoices:raise CommandError('No demo learner enrolments found.')
        invoice=invoices[0]
        approval=Approval.objects.filter(school=school,token=token('bursary')).first()
        if not approval:
            approval=services.request_approval(member,'bursary','Fictional demonstration bursary; not school policy',timezone.localdate(),token('bursary'),invoice=invoice,amount=Decimal('1000'))
        if approval.status=='pending':services.review_request(member,approval,'approve','Fictional demonstration approval')
        if not Payment.objects.filter(school=school,token=token('payment')).exists():
            services.record_payment(member,invoice.learner,'Fictional Demo Parent','mpesa','FICTIONAL-DEMO-001',Decimal('5000'),timezone.localdate(),token('payment'),invoice,Decimal('4000'))
        if not InstalmentPlan.objects.filter(token=token('plan')).exists():
            services.agree_instalments(member,invoice,'Fictional Demo Parent','Illustrative instalments, not agreed school terms',[(date(2027,1,15),Decimal('8000')),(date(2027,2,15),invoice.net-Decimal('8000'))],token('plan'))
        self.stdout.write(self.style.SUCCESS('Fictional finance demo ready: sample fees, three invoices, bursary, payment and instalments. No real payment was made.'))
