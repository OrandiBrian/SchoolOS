from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from core.models import Learner
from core.permissions import school_access
from . import services as ledger
from .forms import (ScheduleForm, InvoiceForm, PaymentForm, AllocationForm, ApprovalForm, ReviewForm, InstalmentForm)
from .models import ZERO, FeeSchedule, Invoice, Payment, Approval, FinanceEvent, Allocation

READ_ROLES={'head','secretary','director','board'}
WRITE_ROLES={'head','secretary'}


def handle(form, operation):
    try:return operation()
    except ValidationError as exc:
        form.add_error(None,' '.join(exc.messages))
    except (IntegrityError,OperationalError):
        form.add_error(None,'Nothing was saved. This may be a duplicate or a simultaneous change. Refresh and review the latest records before retrying.')
    return None


def form_page(request,form,title,help_text=''):
    return render(request,'finance/form.html',{'form':form,'title':title,'help_text':help_text})


@school_access(allowed_roles=READ_ROLES)
@require_http_methods(['GET'])
def dashboard(request):
    invoices=list(Invoice.objects.filter(school=request.school).select_related('learner','term'))
    payments=list(Payment.objects.filter(school=request.school,reversed=False).select_related('credit_owner'))
    outstanding=sum((i.outstanding for i in invoices),ZERO)
    credit=sum((p.credit for p in payments),ZERO)
    collections=sum((p.amount for p in payments if p.method!='opening'),ZERO)
    return render(request,'finance/dashboard.html',{'can_manage':request.membership.role in WRITE_ROLES,
        'outstanding':outstanding,'credit':credit,'collections':collections,'net_balance':outstanding-credit,
        'invoices':invoices if request.membership.role in WRITE_ROLES else [],
        'pending':Approval.objects.filter(school=request.school,status='pending').count(),
        'schedules':FeeSchedule.objects.filter(school=request.school).select_related('term','grade') if request.membership.role in WRITE_ROLES else []})


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def schedule_edit(request):
    form=ScheduleForm(request.POST or None,school=request.school)
    if request.method=='POST' and form.is_valid():
        result=handle(form,lambda:ledger.save_schedule(request.membership,**form.cleaned_data))
        if result:
            messages.success(request,'Fee schedule saved. Previously issued invoices are unchanged.')
            return redirect('finance_dashboard')
    return form_page(request,form,'Set term fees','Choose a grade and term. Saving an existing combination updates future invoices only. Transport is optional when issuing each learner’s invoice.')


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def invoice_create(request):
    form=InvoiceForm(request.POST or None,school=request.school)
    if request.method=='POST' and form.is_valid():
        result=handle(form,lambda:ledger.issue_invoice(request.membership,**form.cleaned_data))
        if result:return redirect('finance_invoice',pk=result.pk)
    return form_page(request,form,'Issue learner invoice','The learner must be enrolled in the selected grade and academic year. Issued amounts are retained permanently.')


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET'])
def invoice_detail(request,pk):
    invoice=get_object_or_404(Invoice,pk=pk,school=request.school)
    return render(request,'finance/invoice.html',{'invoice':invoice,'plan_status':ledger.instalment_status(invoice),
        'adjustments':invoice.adjustments.select_related('approval'),
        'allocations':invoice.allocations.select_related('payment')})


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def payment_create(request):
    form=PaymentForm(request.POST or None,school=request.school)
    if request.method=='POST' and form.is_valid():
        result=handle(form,lambda:ledger.record_payment(request.membership,**form.cleaned_data))
        if result:return redirect('finance_receipt',pk=result.pk)
    return form_page(request,form,'Record payment','Record money received, then allocate all or part to an invoice. Remaining credit belongs to the selected learner and can later be allocated across family invoices. This does not initiate an M-Pesa transaction.')


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET'])
def payments(request):
    return render(request,'finance/payments.html',{'payments':Payment.objects.filter(school=request.school).select_related('credit_owner')})


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET'])
def receipt(request,pk):
    payment=get_object_or_404(Payment,pk=pk,school=request.school)
    return render(request,'finance/receipt.html',{'payment':payment,'allocations':payment.allocations.select_related('invoice__learner')})


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def allocation_create(request,pk):
    payment=get_object_or_404(Payment,pk=pk,school=request.school)
    form=AllocationForm(request.POST or None,school=request.school)
    if request.method=='POST' and form.is_valid():
        result=handle(form,lambda:ledger.allocate(request.membership,payment=payment,**form.cleaned_data))
        if result:return redirect('finance_receipt',pk=payment.pk)
    return form_page(request,form,f'Allocate {payment.number}',f'Available credit: KES {payment.credit:.2f}. An allocation moves existing credit; it does not record another payment.')


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def approval_create(request):
    form=ApprovalForm(request.POST or None,school=request.school)
    if request.method=='POST' and form.is_valid():
        result=handle(form,lambda:ledger.request_approval(request.membership,**form.cleaned_data))
        if result:return redirect('finance_review',pk=result.pk)
    return form_page(request,form,'Request financial approval','Select only the target needed for the request type. Reversals apply to the full selected transaction; leave amount blank. Opening balances must be reconciled against the school’s existing files.')


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET'])
def approvals(request):
    return render(request,'finance/approvals.html',{'approvals':Approval.objects.filter(school=request.school).select_related('requested_by','learner','invoice','payment')})


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def review(request,pk):
    approval=get_object_or_404(Approval,pk=pk,school=request.school)
    form=ReviewForm(request.POST or None)
    if request.method=='POST':
        # Service performs the authoritative head-only check too.
        from django.core.exceptions import PermissionDenied
        if request.membership.role!='head':raise PermissionDenied
        if form.is_valid():
            result=handle(form,lambda:ledger.review_request(request.membership,approval,**form.cleaned_data))
            if result:
                messages.success(request,'Request '+result.status+'.')
                return redirect('finance_review',pk=approval.pk)
    return render(request,'finance/review.html',{'approval':approval,'form':form,'can_review':request.membership.role=='head' and approval.status=='pending'})


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET','POST'])
def plan_create(request,pk):
    invoice=get_object_or_404(Invoice,pk=pk,school=request.school)
    form=InstalmentForm(request.POST or None,school=request.school)
    if request.method=='POST' and form.is_valid():
        result=handle(form,lambda:ledger.agree_instalments(request.membership,invoice=invoice,**form.cleaned_data))
        if result:return redirect('finance_invoice',pk=invoice.pk)
    return form_page(request,form,f'Instalment agreement · {invoice.number}',f'Net invoice charge: KES {invoice.net:.2f}. Each new agreement supersedes the schedule shown for this invoice; prior versions remain in the history.')


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET'])
def statement(request,pk):
    learner=get_object_or_404(Learner,pk=pk,school=request.school)
    context=ledger.learner_balances(learner)
    context.update({'learner':learner,'allocations':Allocation.objects.filter(invoice__learner=learner,invoice__school=request.school).select_related('payment','invoice')})
    return render(request,'finance/statement.html',context)


@school_access(allowed_roles=WRITE_ROLES)
@require_http_methods(['GET'])
def audit(request):
    from django.core.paginator import Paginator
    page=Paginator(FinanceEvent.objects.filter(school=request.school).select_related('actor'),50).get_page(request.GET.get('page'))
    return render(request,'finance/audit.html',{'page':page})
