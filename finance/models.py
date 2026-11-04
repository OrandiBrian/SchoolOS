import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

ZERO = Decimal('0.00')


def total(query, field='amount'):
    return query.aggregate(value=Sum(field))['value'] or ZERO


class SchoolCounter(models.Model):
    school = models.OneToOneField('core.School', on_delete=models.PROTECT)
    next_invoice = models.PositiveIntegerField(default=1)
    next_receipt = models.PositiveIntegerField(default=1)


class FeeSchedule(models.Model):
    school = models.ForeignKey('core.School', on_delete=models.PROTECT)
    term = models.ForeignKey('core.Term', on_delete=models.PROTECT)
    grade = models.ForeignKey('core.Grade', on_delete=models.PROTECT)
    tuition = models.DecimalField(max_digits=12, decimal_places=2)
    transport = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['school','term','grade'], name='one_fee_schedule_per_grade_term'),
                       models.CheckConstraint(condition=Q(tuition__gt=0, transport__gte=0), name='valid_fee_schedule_amounts')]

    def __str__(self):
        return f'{self.grade} · {self.term} · KES {self.tuition}'


class Invoice(models.Model):
    school = models.ForeignKey('core.School', on_delete=models.PROTECT)
    learner = models.ForeignKey('core.Learner', on_delete=models.PROTECT)
    term = models.ForeignKey('core.Term', on_delete=models.PROTECT, null=True, blank=True)
    number = models.CharField(max_length=40)
    kind = models.CharField(max_length=16, default='term')
    voided = models.BooleanField(default=False)
    description = models.CharField(max_length=200)
    tuition = models.DecimalField(max_digits=12, decimal_places=2)
    transport = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    due_date = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    token = models.UUIDField(default=uuid.uuid4)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['school','number'], name='unique_invoice_number'),
                       models.UniqueConstraint(fields=['school','token'], name='unique_invoice_submission'),
                       models.UniqueConstraint(fields=['learner','term'], condition=Q(kind='term', voided=False), name='one_term_invoice_per_learner'),
                       models.CheckConstraint(condition=Q(tuition__gt=0, transport__gte=0), name='valid_invoice_amounts')]

    @property
    def gross(self): return self.tuition + self.transport
    @property
    def assistance(self): return total(self.adjustments.filter(reversed=False))
    @property
    def net(self): return self.gross - self.assistance if not self.voided else ZERO
    @property
    def paid(self): return total(self.allocations.filter(payment__reversed=False)) if not self.voided else ZERO
    @property
    def outstanding(self): return self.net - self.paid
    def __str__(self): return f'{self.number} · {self.learner.full_name}'


class Payment(models.Model):
    METHODS = [('cash','Cash'), ('bank','Bank'), ('mpesa','M-Pesa'), ('opening','Opening credit')]
    school = models.ForeignKey('core.School', on_delete=models.PROTECT)
    credit_owner = models.ForeignKey('core.Learner', on_delete=models.PROTECT)
    number = models.CharField(max_length=40)
    payer = models.CharField(max_length=160)
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    reversed = models.BooleanField(default=False)
    token = models.UUIDField(default=uuid.uuid4)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['school','number'], name='unique_receipt_number'),
                       models.UniqueConstraint(fields=['school','token'], name='unique_payment_submission'),
                       models.UniqueConstraint(fields=['school','method','reference'], condition=~Q(reference=''), name='unique_payment_reference'),
                       models.CheckConstraint(condition=Q(amount__gt=0), name='positive_payment')]

    @property
    def allocated(self): return total(self.allocations.filter(invoice__voided=False)) if not self.reversed else ZERO
    @property
    def credit(self): return self.amount - self.allocated if not self.reversed else ZERO
    def __str__(self): return f'{self.number} · {self.payer} · KES {self.amount}'


class Allocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='allocations')
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='allocations')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=200)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='positive_allocation')]


class Approval(models.Model):
    KINDS = [('discount','Discount'), ('bursary','Bursary'), ('opening_debit','Opening balance owed'),
             ('opening_credit','Opening credit'), ('payment_reversal','Payment reversal'), ('invoice_reversal','Invoice reversal'), ('adjustment_reversal','Assistance reversal')]
    school = models.ForeignKey('core.School', on_delete=models.PROTECT)
    kind = models.CharField(max_length=24, choices=KINDS)
    learner = models.ForeignKey('core.Learner', on_delete=models.PROTECT, null=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, null=True, blank=True)
    adjustment = models.ForeignKey('Adjustment', on_delete=models.PROTECT, null=True, blank=True, related_name='reversal_requests')
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    effective_date = models.DateField()
    reason = models.CharField(max_length=500)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='finance_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, default='pending')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='finance_reviews')
    reviewed_at = models.DateTimeField(null=True)
    review_note = models.CharField(max_length=500, blank=True)
    token = models.UUIDField(default=uuid.uuid4)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['school','token'], name='unique_finance_request_submission')]


class Adjustment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='adjustments')
    approval = models.OneToOneField(Approval, on_delete=models.PROTECT, related_name='issued_adjustment')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reversed = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='positive_assistance')]

    def __str__(self): return f'{self.invoice.number} · {self.approval.get_kind_display()} · KES {self.amount}'


class InstalmentPlan(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='plans')
    agreed_with = models.CharField(max_length=160)
    notes = models.CharField(max_length=500, blank=True)
    charge_at_agreement = models.DecimalField(max_digits=12, decimal_places=2)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class Instalment(models.Model):
    plan = models.ForeignKey(InstalmentPlan, on_delete=models.PROTECT, related_name='items')
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    class Meta:
        ordering = ['due_date', 'pk']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='positive_instalment')]


class FinanceEvent(models.Model):
    school = models.ForeignKey('core.School', on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-pk']
