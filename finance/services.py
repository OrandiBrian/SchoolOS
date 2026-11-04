from datetime import date
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from core.models import School, AnnualEnrollment
from core.permissions import active_membership
from .models import (ZERO, SchoolCounter, FeeSchedule, Invoice, Payment, Allocation,
                     Approval, Adjustment, InstalmentPlan, Instalment, FinanceEvent)


def money(value, allow_zero=False):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(Decimal('.01')) or amount > Decimal('9999999999.99'):
            raise ValueError
        if amount < 0 or (not allow_zero and amount == 0):
            raise ValueError
        return amount.quantize(Decimal('.01'))
    except (ValueError, InvalidOperation, TypeError):
        raise ValidationError('Enter a positive KES amount with at most two decimal places.' if not allow_zero else 'Enter a non-negative KES amount with at most two decimal places.')


def lock_school(member, head=False):
    # Every monetary mutation serializes on one school row on PostgreSQL.
    School.objects.select_for_update().get(pk=member.school_id)
    current = active_membership(member.user, member.school_id)
    if not current or current.role not in ({'head'} if head else {'head','secretary'}):
        raise PermissionDenied
    return current


def owns(member, obj, school_id=None):
    actual = school_id if school_id is not None else obj.school_id
    if actual != member.school_id:
        raise PermissionDenied


def event(member, action, **detail):
    FinanceEvent.objects.create(school=member.school, actor=member.user, action=action, detail=detail)


def number(member, field, prefix):
    counter, _ = SchoolCounter.objects.get_or_create(school=member.school)
    sequence = getattr(counter, field)
    setattr(counter, field, sequence+1)
    counter.save(update_fields=[field])
    return f'{prefix}-{sequence:06d}'


def valid_date(day):
    if not isinstance(day, date) or day > timezone.localdate():
        raise ValidationError('Use today or an earlier date for payments and opening balances.')


@transaction.atomic
def save_schedule(member, term, grade, tuition, transport):
    member = lock_school(member)
    owns(member, term, term.academic_year.school_id)
    owns(member, grade)
    tuition, transport = money(tuition), money(transport, True)
    schedule, _ = FeeSchedule.objects.get_or_create(school=member.school, term=term, grade=grade, defaults={'tuition':tuition,'transport':transport})
    before = {'tuition':str(schedule.tuition), 'transport':str(schedule.transport)}
    schedule.tuition, schedule.transport = tuition, transport
    schedule.full_clean()
    schedule.save()
    event(member, 'Fee schedule saved', schedule=schedule.pk, before=before, tuition=str(tuition), transport=str(transport))
    return schedule


@transaction.atomic
def issue_invoice(member, learner, schedule, due_date, include_transport, token):
    member = lock_school(member)
    owns(member, learner); owns(member, schedule)
    schedule = FeeSchedule.objects.select_related('term__academic_year', 'grade').get(pk=schedule.pk)
    existing = Invoice.objects.filter(school=member.school, token=token).first()
    if existing: return existing
    if not AnnualEnrollment.objects.filter(learner=learner, academic_year=schedule.term.academic_year, learning_group__grade=schedule.grade).exists():
        raise ValidationError('Choose the fee schedule matching this learner’s grade and academic year.')
    if Invoice.objects.filter(learner=learner, term=schedule.term, kind='term', voided=False).exists():
        raise ValidationError('This learner already has an invoice for that term.')
    invoice = Invoice(school=member.school, learner=learner, term=schedule.term, number=number(member,'next_invoice','INV'), description=f'{schedule.grade.name} · {schedule.term.name}', tuition=schedule.tuition, transport=schedule.transport if include_transport else ZERO, due_date=due_date, created_by=member.user, token=token)
    invoice.full_clean(); invoice.save()
    event(member, 'Invoice issued', invoice=invoice.pk, number=invoice.number, gross=str(invoice.gross))
    return invoice


@transaction.atomic
def allocate(member, payment, invoice, amount, reason, token):
    member = lock_school(member)
    owns(member, payment); owns(member, invoice)
    payment = Payment.objects.get(pk=payment.pk)
    invoice = Invoice.objects.get(pk=invoice.pk)
    existing = Allocation.objects.filter(token=token).first()
    if existing:
        if existing.payment_id != payment.pk or existing.invoice_id != invoice.pk:
            raise ValidationError('Submission token already used. Reload the form.')
        return existing
    amount = money(amount)
    if not reason.strip(): raise ValidationError('Give an allocation reason, especially when splitting a family payment.')
    if payment.reversed: raise ValidationError('A reversed payment cannot be allocated.')
    if invoice.voided: raise ValidationError('A reversed invoice cannot receive allocations.')
    if amount > payment.credit: raise ValidationError('The allocation exceeds available payment credit.')
    if amount > invoice.outstanding: raise ValidationError('The allocation exceeds the invoice balance.')
    result = Allocation(payment=payment, invoice=invoice, amount=amount, reason=reason, token=token)
    result.full_clean(); result.save()
    event(member, 'Payment allocated', payment=payment.pk, invoice=invoice.pk, amount=str(amount), reason=reason)
    return result


@transaction.atomic
def record_payment(member, credit_owner, payer, method, reference, amount, received_on, token, invoice=None, allocation_amount=None):
    member = lock_school(member)
    owns(member, credit_owner)
    if invoice: owns(member, invoice)
    existing = Payment.objects.filter(school=member.school, token=token).first()
    if existing: return existing
    if method not in {'cash','bank','mpesa'}: raise ValidationError('Choose cash, bank or M-Pesa.')
    amount = money(amount)
    valid_date(received_on)
    reference = reference.strip().upper()
    if method in {'bank','mpesa'} and not reference: raise ValidationError('Bank and M-Pesa payments require a transaction reference.')
    if reference and Payment.objects.filter(school=member.school, method=method, reference=reference).exists():
        raise ValidationError('This transaction reference is already recorded, including any reversed receipt.')
    payment = Payment(school=member.school, credit_owner=credit_owner, payer=payer, method=method, reference=reference, amount=amount, received_on=received_on, number=number(member,'next_receipt','RCT'), created_by=member.user, token=token)
    payment.full_clean(); payment.save()
    if invoice:
        if allocation_amount is None: raise ValidationError('Enter the amount to allocate to the selected invoice.')
        allocate(member,payment,invoice,allocation_amount,'Initial payment allocation',token)
    elif allocation_amount:
        raise ValidationError('Choose an invoice for the allocation, or leave both fields blank.')
    event(member, 'Payment recorded', payment=payment.pk, amount=str(amount), number=payment.number, method=method)
    return payment


def validate_request(member, kind, learner, invoice, payment, adjustment, amount):
    if kind not in dict(Approval.KINDS): raise ValidationError('Invalid request type.')
    for obj in [learner, invoice, payment]:
        if obj: owns(member,obj)
    if adjustment: owns(member,adjustment,adjustment.invoice.school_id)
    if kind in {'discount','bursary'}:
        if not invoice or learner or payment or adjustment: raise ValidationError('Assistance requires only an invoice target.')
        if invoice.voided: raise ValidationError('A reversed invoice cannot receive assistance.')
        amount = money(amount)
        if amount > invoice.outstanding: raise ValidationError('Assistance cannot exceed the unpaid invoice balance.')
    elif kind in {'opening_debit','opening_credit'}:
        if not learner or invoice or payment or adjustment: raise ValidationError('An opening balance requires only a learner target.')
        amount = money(amount)
    elif kind == 'invoice_reversal':
        if not invoice or learner or payment or adjustment or amount is not None: raise ValidationError('An invoice reversal requires only an invoice target; leave amount blank.')
        if invoice.voided: raise ValidationError('This invoice is already reversed.')
    elif kind == 'payment_reversal':
        if not payment or invoice or learner or adjustment or amount is not None: raise ValidationError('A payment reversal requires only a payment target; leave amount blank.')
        if payment.reversed: raise ValidationError('This payment has already been reversed.')
    else:
        if not adjustment or learner or invoice or payment or amount is not None: raise ValidationError('An assistance reversal requires only an assistance target; leave amount blank.')
        if adjustment.reversed: raise ValidationError('This assistance has already been reversed.')
    return amount


@transaction.atomic
def request_approval(member, kind, reason, effective_date, token, learner=None, invoice=None, payment=None, adjustment=None, amount=None):
    member = lock_school(member)
    existing = Approval.objects.filter(school=member.school,token=token).first()
    if existing: return existing
    amount = validate_request(member,kind,learner,invoice,payment,adjustment,amount)
    valid_date(effective_date)
    if not reason.strip(): raise ValidationError('Document the reason and source record for this request.')
    result = Approval(school=member.school,kind=kind,reason=reason,effective_date=effective_date,token=token,learner=learner,invoice=invoice,payment=payment,adjustment=adjustment,amount=amount,requested_by=member.user)
    result.full_clean(exclude=['reviewed_by','reviewed_at']); result.save()
    event(member,'Approval requested',request=result.pk,kind=kind,reason=reason)
    return result


@transaction.atomic
def review_request(member, request, decision, note):
    member = lock_school(member,head=True)
    owns(member,request)
    request = Approval.objects.select_related('invoice','payment','adjustment__invoice','learner').get(pk=request.pk)
    if request.status != 'pending': raise ValidationError('This request has already been reviewed.')
    if decision not in {'approve','reject'}: raise ValidationError('Choose approve or reject.')
    if not note.strip() or len(note)>500: raise ValidationError('Enter a review note of at most 500 characters.')
    if decision == 'approve':
        validate_request(member,request.kind,request.learner,request.invoice,request.payment,request.adjustment,request.amount)
        if request.kind in {'discount','bursary'}:
            Adjustment.objects.create(invoice=request.invoice,approval=request,amount=request.amount)
        elif request.kind == 'invoice_reversal':
            request.invoice.voided = True
            request.invoice.save(update_fields=['voided'])
        elif request.kind == 'payment_reversal':
            request.payment.reversed = True
            request.payment.save(update_fields=['reversed'])
        elif request.kind == 'adjustment_reversal':
            request.adjustment.reversed = True
            request.adjustment.save(update_fields=['reversed'])
        elif request.kind == 'opening_debit':
            Invoice.objects.create(school=member.school,learner=request.learner,number=number(member,'next_invoice','INV'),kind='opening',description='Verified opening balance',tuition=request.amount,transport=ZERO,due_date=request.effective_date,created_by=member.user,token=request.token)
        else:
            Payment.objects.create(school=member.school,credit_owner=request.learner,payer='Verified opening credit',method='opening',amount=request.amount,received_on=request.effective_date,number=number(member,'next_receipt','CRD'),created_by=member.user,token=request.token)
    request.status = 'approved' if decision=='approve' else 'rejected'
    request.reviewed_by = member.user
    request.reviewed_at = timezone.now()
    request.review_note = note
    request.save(update_fields=['status','reviewed_by','reviewed_at','review_note'])
    event(member,'Request '+request.status,request=request.pk,kind=request.kind,note=note)
    return request


@transaction.atomic
def agree_instalments(member, invoice, agreed_with, notes, rows, token):
    member = lock_school(member)
    owns(member,invoice)
    invoice = Invoice.objects.get(pk=invoice.pk)
    existing = InstalmentPlan.objects.filter(token=token).first()
    if existing:
        if existing.invoice_id != invoice.pk: raise ValidationError('Submission token already used.')
        return existing
    if invoice.voided: raise ValidationError('A reversed invoice cannot have a new agreement.')
    if not rows or len(rows)>24: raise ValidationError('Provide between 1 and 24 instalments.')
    amounts = [money(amount) for day,amount in rows]
    if sum(amounts,ZERO) != invoice.net: raise ValidationError(f'Instalments must total the net invoice charge: KES {invoice.net:.2f}. Payments already made count toward the earliest instalments.')
    if len({day for day,amount in rows}) != len(rows): raise ValidationError('Use a different date for each instalment.')
    plan = InstalmentPlan(invoice=invoice,agreed_with=agreed_with,notes=notes,charge_at_agreement=invoice.net,created_by=member.user,token=token)
    plan.full_clean(); plan.save()
    for (day,_),amount in zip(rows,amounts):
        item=Instalment(plan=plan,due_date=day,amount=amount); item.full_clean(); item.save()
    event(member,'Instalment agreement recorded',invoice=invoice.pk,plan=plan.pk,charge=str(invoice.net),agreed_with=agreed_with)
    return plan


def instalment_status(invoice):
    plan=invoice.plans.first()
    if not plan: return None
    remaining_paid=invoice.paid
    rows=[]
    overdue=ZERO
    for item in plan.items.all():
        applied=min(remaining_paid,item.amount)
        remaining_paid-=applied
        outstanding=item.amount-applied
        late=item.due_date<timezone.localdate() and outstanding>0
        if late: overdue+=outstanding
        rows.append({'due_date':item.due_date,'amount':item.amount,'paid':applied,'outstanding':outstanding,'overdue':late})
    return {'plan':plan,'rows':rows,'needs_revision':plan.charge_at_agreement!=invoice.net,'overdue':overdue}


def learner_balances(learner):
    invoices=list(Invoice.objects.filter(school=learner.school,learner=learner).select_related('term'))
    credits=[p for p in Payment.objects.filter(school=learner.school,credit_owner=learner,reversed=False) if p.credit>0]
    debt=sum((i.outstanding for i in invoices),ZERO)
    credit=sum((p.credit for p in credits),ZERO)
    return {'invoices':invoices,'credits':credits,'debt':debt,'credit':credit,'balance':debt-credit}
