# Django 6.0 Jazzmin Pagination Fix

## Problem
Django 6.0 introduced a breaking change where `format_html()` now requires at least one argument (args or kwargs). The jazzmin package (v3.0.1) uses `format_html(html_str)` which causes a `TypeError: args or kwargs must be provided` error when accessing admin list views with pagination.

## Solution
This fix patches the jazzmin package's `jazzmin_paginator_number` template tag to use `mark_safe()` instead of `format_html()` for Django 6.0 compatibility.

### Implementation

1. **Automated Patch Script** (`fix_jazzmin.sh`):
   - Automatically locates the jazzmin package installation
   - Patches line 256 in `jazzmin/templatetags/jazzmin.py`
   - Replaces `return format_html(html_str)` with `return mark_safe(html_str)`

2. **Usage**:
   ```bash
   # Run after installing requirements.txt
   ./fix_jazzmin.sh
   ```

## Why This Works
- `mark_safe()` marks a string as safe for HTML output without requiring additional arguments
- The HTML string is already properly formatted by the template tag
- No security impact since the string is built from trusted sources (Django's own ChangeList object)

## Files Changed
- `fix_jazzmin.sh` - New patch script
- `finoa/settings.py` - Updated INSTALLED_APPS order (core before jazzmin) for template tag override precedence
- `core/templatetags/__init__.py` - Template tags package init
- `core/templatetags/jazzmin.py` - Custom jazzmin template tag override (fallback solution)
- `core/apps.py` - Reverted to original (monkey patch approach removed)

## Deployment
Run the patch script as part of your deployment process:
```bash
pip install -r requirements.txt
./fix_jazzmin.sh
python manage.py runserver
```

## Alternative Solutions Considered
1. ✗ Monkey patching in `CoreConfig.ready()` - Doesn't work because template tags are loaded before AppConfig.ready()
2. ✗ Custom template tag override - Doesn't work reliably due to Python module caching
3. ✓ Direct file patch via shell script - Works reliably and is easy to integrate into deployment

## Note
This is a temporary fix until jazzmin releases a Django 6.0 compatible version. Monitor the jazzmin GitHub repository for official updates.
