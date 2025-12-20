"""
Tests for Django 6.0 compatibility fixes in core.templatetags.jazzmin
"""
from django.contrib.admin.views.main import ChangeList
from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.admin import ModelAdmin

from core.templatetags.jazzmin import jazzmin_paginator_number


class JazzminPaginatorNumberTestCase(TestCase):
    """Test the jazzmin_paginator_number template tag for Django 6.0 compatibility."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.site = AdminSite()
        
    def test_jazzmin_paginator_number_returns_safe_html(self):
        """Test that jazzmin_paginator_number returns SafeText without errors."""
        # Create a mock request
        request = self.factory.get('/admin/auth/user/')
        request.user = User(username='admin', is_staff=True, is_superuser=True)
        
        # Create a ModelAdmin instance
        model_admin = ModelAdmin(User, self.site)
        
        # Create a ChangeList - this would normally be done by Django admin
        changelist = ChangeList(
            request=request,
            model=User,
            list_display=['username'],
            list_display_links=['username'],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=[],
            list_per_page=100,
            list_max_show_all=200,
            list_editable=[],
            model_admin=model_admin,
            sortable_by=[],
            search_help_text=None,
        )
        
        # Test the template tag with different page numbers
        # This should not raise "TypeError: args or kwargs must be provided"
        try:
            result = jazzmin_paginator_number(changelist, 1)
            self.assertIsNotNone(result)
            self.assertIn('page-item', str(result))
        except TypeError as e:
            if "args or kwargs must be provided" in str(e):
                self.fail("Template tag still uses format_html incorrectly")
            raise
    
    def test_jazzmin_paginator_number_start_page(self):
        """Test pagination rendering for the first page."""
        request = self.factory.get('/admin/auth/user/')
        request.user = User(username='admin', is_staff=True, is_superuser=True)
        
        model_admin = ModelAdmin(User, self.site)
        changelist = ChangeList(
            request=request,
            model=User,
            list_display=['username'],
            list_display_links=['username'],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=[],
            list_per_page=100,
            list_max_show_all=200,
            list_editable=[],
            model_admin=model_admin,
            sortable_by=[],
            search_help_text=None,
        )
        
        result = jazzmin_paginator_number(changelist, 1)
        self.assertIn('previous', str(result))
        self.assertIn('«', str(result))
