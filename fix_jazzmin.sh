#!/bin/bash
# Fix jazzmin pagination template tag for Django 6.0 compatibility
# This script patches the jazzmin package to use mark_safe instead of format_html
# Run this script after installing requirements.txt

JAZZMIN_FILE=$(python -c "import jazzmin.templatetags.jazzmin as j; import os; print(os.path.dirname(j.__file__) + '/jazzmin.py')")

if [ -f "$JAZZMIN_FILE" ]; then
    echo "Patching $JAZZMIN_FILE for Django 6.0 compatibility..."
    sed -i '256s/return format_html(html_str)/return mark_safe(html_str)/' "$JAZZMIN_FILE"
    echo "Patch applied successfully."
else
    echo "Error: jazzmin templatetags file not found at $JAZZMIN_FILE"
    exit 1
fi
