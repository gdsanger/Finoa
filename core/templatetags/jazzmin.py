"""
Django 6.0 compatibility fix for jazzmin pagination template tag.

This module overrides the jazzmin_paginator_number template tag to use
mark_safe() instead of format_html() for Django 6.0 compatibility.

Django 6.0 changed format_html() to require at least one argument for formatting.
Since the html_str is already properly formatted and doesn't need escaping,
we use mark_safe() instead.
"""

from django.contrib.admin.views.main import PAGE_VAR, ChangeList
from django.template import Library
from django.utils.safestring import SafeText, mark_safe

register = Library()


@register.simple_tag
def jazzmin_paginator_number(change_list: ChangeList, i: int) -> SafeText:
    """
    Generate an individual page index link in a paginated list.
    
    This is a Django 6.0 compatible version that uses mark_safe() instead of
    format_html() to avoid the "args or kwargs must be provided" TypeError.
    """
    html_str = ""
    start = i == 1
    end = i == change_list.paginator.num_pages
    spacer = i in (".", "…")
    current_page = i == change_list.page_num

    if start:
        link = change_list.get_query_string({PAGE_VAR: change_list.page_num - 1}) if change_list.page_num > 1 else "#"
        html_str += """
        <li class="page-item previous {disabled}">
            <a class="page-link" href="{link}" data-dt-idx="0" tabindex="0">«</a>
        </li>
        """.format(link=link, disabled="disabled" if link == "#" else "")

    if current_page:
        html_str += """
        <li class="page-item active">
            <a class="page-link" href="javascript:void(0);" data-dt-idx="3" tabindex="0">{num}</a>
        </li>
        """.format(num=i)
    elif spacer:
        html_str += """
        <li class="page-item">
            <a class="page-link" href="javascript:void(0);" data-dt-idx="3" tabindex="0">… </a>
        </li>
        """
    else:
        query_string = change_list.get_query_string({PAGE_VAR: i})
        end_class = "end" if end else ""
        html_str += """
            <li class="page-item">
            <a href="{query_string}" class="page-link {end}" data-dt-idx="3" tabindex="0">{num}</a>
            </li>
        """.format(num=i, query_string=query_string, end=end_class)

    if end:
        link = change_list.get_query_string({PAGE_VAR: change_list.page_num + 1}) if change_list.page_num < i else "#"
        html_str += """
        <li class="page-item next {disabled}">
            <a class="page-link" href="{link}" data-dt-idx="7" tabindex="0">»</a>
        </li>
        """.format(link=link, disabled="disabled" if link == "#" else "")

    return mark_safe(html_str)
