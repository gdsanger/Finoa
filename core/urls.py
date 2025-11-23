from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('accounts/', views.accounts, name='accounts'),
    path('accounts/<int:account_id>/', views.account_detail, name='account_detail'),
    path('accounts/<int:account_id>/reconcile/', views.reconcile_balance, name='reconcile_balance'),
    path('monthly/', views.monthly_view, name='monthly_view'),
    path('analytics/categories/', views.category_analytics, name='category_analytics'),
    path('payees/', views.payees, name='payees'),
    path('documents/', views.document_list, name='document_list'),
    path('documents/review/', views.document_review_list, name='document_review_list'),
    path('debug/', views.debug_view, name='debug_view'),
    path('documents/review/<int:document_id>/', views.document_review_detail, name='document_review_detail'),
    path('due-bookings/', views.due_bookings, name='due_bookings'),
    path('bookings/<int:booking_id>/mark-booked/', views.mark_booking_as_booked, name='mark_booking_as_booked'),
]
