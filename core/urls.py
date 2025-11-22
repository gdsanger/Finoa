from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('accounts/', views.accounts, name='accounts'),
    path('monthly/', views.monthly_view, name='monthly_view'),
    path('analytics/categories/', views.category_analytics, name='category_analytics'),
]
