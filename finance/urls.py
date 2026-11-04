from django.urls import path
from . import views
urlpatterns=[
    path('',views.dashboard,name='finance_dashboard'),
    path('fees/',views.schedule_edit,name='finance_schedule'),
    path('invoices/new/',views.invoice_create,name='finance_invoice_create'),
    path('invoices/<int:pk>/',views.invoice_detail,name='finance_invoice'),
    path('invoices/<int:pk>/instalments/',views.plan_create,name='finance_plan'),
    path('payments/',views.payments,name='finance_payments'),
    path('payments/new/',views.payment_create,name='finance_payment_create'),
    path('payments/<int:pk>/',views.receipt,name='finance_receipt'),
    path('payments/<int:pk>/allocate/',views.allocation_create,name='finance_allocate'),
    path('approvals/',views.approvals,name='finance_approvals'),
    path('approvals/new/',views.approval_create,name='finance_approval_create'),
    path('approvals/<int:pk>/',views.review,name='finance_review'),
    path('learners/<int:pk>/statement/',views.statement,name='finance_statement'),
    path('history/',views.audit,name='finance_audit'),
]
