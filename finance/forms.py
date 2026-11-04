import uuid
from datetime import date
from decimal import Decimal
from django import forms
from django.utils import timezone
from core.forms import StyledForm
from core.models import Learner, Term, Grade
from .models import FeeSchedule, Invoice, Payment, Approval, Adjustment


def amount_field(required=True, minimum=Decimal('.01')):
    return forms.DecimalField(max_digits=12, decimal_places=2, min_value=minimum, required=required, label='Amount (KES)')


def day_field(label, initial=None):
    return forms.DateField(label=label, initial=initial, widget=forms.DateInput(attrs={'type':'date'}))


class ScopedForm(StyledForm):
    def __init__(self,*args,school,**kwargs):
        super().__init__(*args,**kwargs)
        self.school=school
        queries={
            'learner':Learner.objects.filter(school=school),
            'credit_owner':Learner.objects.filter(school=school),
            'term':Term.objects.filter(academic_year__school=school).select_related('academic_year'),
            'grade':Grade.objects.filter(school=school),
            'schedule':FeeSchedule.objects.filter(school=school).select_related('term','grade'),
            'invoice':Invoice.objects.filter(school=school).select_related('learner'),
            'payment':Payment.objects.filter(school=school,reversed=False),
            'adjustment':Adjustment.objects.filter(invoice__school=school,reversed=False).select_related('invoice','approval'),
        }
        for key,query in queries.items():
            if key in self.fields:self.fields[key].queryset=query


class TokenForm(ScopedForm):
    token=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)


class ScheduleForm(ScopedForm):
    term=forms.ModelChoiceField(queryset=Term.objects.none())
    grade=forms.ModelChoiceField(queryset=Grade.objects.none())
    tuition=amount_field()
    tuition.label='Tuition fees per term (KES)'
    transport=amount_field(minimum=Decimal('0'))
    transport.label='Optional transport per term (KES)'
    transport.initial=Decimal('0')


class InvoiceForm(TokenForm):
    learner=forms.ModelChoiceField(queryset=Learner.objects.none())
    schedule=forms.ModelChoiceField(queryset=FeeSchedule.objects.none())
    due_date=day_field('Payment due date')
    include_transport=forms.BooleanField(required=False,label='Include transport at the configured term rate')


class PaymentForm(TokenForm):
    credit_owner=forms.ModelChoiceField(queryset=Learner.objects.none(),label='Learner who owns any remaining credit')
    payer=forms.CharField(max_length=160,label='Name of payer')
    method=forms.ChoiceField(choices=Payment.METHODS[:3])
    reference=forms.CharField(max_length=100,required=False,label='Transaction reference',help_text='Required for bank or M-Pesa. Recorded references cannot be reused.')
    amount=amount_field()
    received_on=day_field('Date received',timezone.localdate)
    invoice=forms.ModelChoiceField(queryset=Invoice.objects.none(),required=False,label='Allocate to invoice (optional)')
    allocation_amount=amount_field(required=False)
    allocation_amount.label='Initial allocation (KES, optional)'


class AllocationForm(TokenForm):
    invoice=forms.ModelChoiceField(queryset=Invoice.objects.none())
    amount=amount_field()
    reason=forms.CharField(max_length=200,help_text='Explain the allocation, including a sibling’s name if sharing a family payment.')


class ApprovalForm(TokenForm):
    kind=forms.ChoiceField(choices=Approval.KINDS)
    learner=forms.ModelChoiceField(queryset=Learner.objects.none(),required=False,label='Learner (opening balances only)')
    invoice=forms.ModelChoiceField(queryset=Invoice.objects.none(),required=False,label='Invoice (discount, bursary or invoice reversal)')
    payment=forms.ModelChoiceField(queryset=Payment.objects.none(),required=False,label='Payment (payment reversal only)')
    adjustment=forms.ModelChoiceField(queryset=Adjustment.objects.none(),required=False,label='Assistance (assistance reversal only)')
    amount=amount_field(required=False)
    effective_date=day_field('Effective date / opening balance date',timezone.localdate)
    reason=forms.CharField(max_length=500,widget=forms.Textarea(attrs={'rows':3}),help_text='State the reason and source record. The head will review before balances change.')


class ReviewForm(StyledForm):
    decision=forms.ChoiceField(choices=[('approve','Approve'),('reject','Reject')])
    note=forms.CharField(max_length=500,widget=forms.Textarea(attrs={'rows':3}),label='Review note')


class InstalmentForm(TokenForm):
    agreed_with=forms.CharField(max_length=160,label='Agreed with (parent/guardian name)')
    notes=forms.CharField(max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))
    rows=forms.CharField(label='Instalment dates and amounts',widget=forms.Textarea(attrs={'rows':5,'placeholder':'2027-01-10, 10000.00\n2027-02-10, 5000.00'}),help_text='One YYYY-MM-DD, amount per line. Total must equal the net invoice charge, including amounts already paid.')

    def clean_rows(self):
        lines=self.cleaned_data['rows'].strip().splitlines()
        if len(lines)>24:raise forms.ValidationError('Use at most 24 instalments.')
        result=[]
        for index,line in enumerate(lines,1):
            try:
                day,value=line.split(',')
                parsed=date.fromisoformat(day.strip())
                amount=amount_field().clean(value.strip())
                result.append((parsed,amount))
            except (ValueError, forms.ValidationError):
                raise forms.ValidationError(f'Line {index}: enter YYYY-MM-DD, positive KES amount.')
        return result
