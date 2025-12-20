# Django 6.0 Jazzmin Pagination Fix

## Problem
Django 6.0 introduced a breaking change where `format_html()` now requires at least one argument (args or kwargs). The jazzmin package (v3.0.1) uses `format_html(html_str)` which causes a `TypeError: args or kwargs must be provided` error when accessing admin list views with pagination.

### Error Example
```
TypeError at /admin/core/booking/
args or kwargs must be provided.

Exception Location: /opt/Finoa/.venv/lib/python3.12/site-packages/django/utils/html.py, line 137, in format_html
```

## Solution
This fix patches the jazzmin package's `jazzmin_paginator_number` template tag to use `mark_safe()` instead of `format_html()` for Django 6.0 compatibility.

### Implementation

**Automated Patch Script** (`fix_jazzmin.sh`):
- Automatically locates the jazzmin package installation
- Patches line 256 in `jazzmin/templatetags/jazzmin.py`
- Replaces `return format_html(html_str)` with `return mark_safe(html_str)`

### Usage
```bash
# Run after installing requirements.txt
cd /path/to/Finoa
pip install -r requirements.txt
./fix_jazzmin.sh
python manage.py runserver
```

## Why This Works
- `mark_safe()` marks a string as safe for HTML output without requiring additional arguments
- The HTML string is already properly formatted by the template tag
- No security impact since the string is built from trusted sources (Django's own ChangeList object)
- The patch is applied directly to the installed jazzmin package

## Deployment
Run the patch script as part of your deployment process:
```bash
pip install -r requirements.txt
./fix_jazzmin.sh
python manage.py runserver
```

**Note**: The patch needs to be reapplied after each time you reinstall or upgrade the jazzmin package.

## Alternative Solutions Considered
1. ✗ Monkey patching in `CoreConfig.ready()` - Doesn't work because template tags are loaded before AppConfig.ready()
2. ✗ Custom template tag override - Doesn't work because Django loads the first matching template tag library name from INSTALLED_APPS, and both modules use the same name "jazzmin"
3. ✓ Direct file patch via shell script - Works reliably and is easy to integrate into deployment

## Technical Details
The issue is in `/path/to/site-packages/jazzmin/templatetags/jazzmin.py` at line 256:
```python
# Before (causes error in Django 6.0):
return format_html(html_str)

# After (works in Django 6.0):
return mark_safe(html_str)
```

## Note
This is a temporary fix until jazzmin releases a Django 6.0 compatible version. Monitor the [jazzmin GitHub repository](https://github.com/farridav/django-jazzmin) for official updates.
