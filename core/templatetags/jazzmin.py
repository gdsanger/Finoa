"""
Custom jazzmin template tags to override django-jazzmin for Django 6.0 compatibility.

This file provides fixes for template tags that are incompatible with Django 6.0.
Specifically, it fixes the jazzmin_paginator_number tag which was calling format_html
without any format arguments, which is not allowed in Django 6.0.
"""

from typing import Union

from django import template
from django.contrib.admin.views.main import ChangeList, PAGE_VAR
from django.utils.safestring import SafeText, mark_safe

register = template.Library()


@register.simple_tag
def jazzmin_paginator_number(change_list: ChangeList, i: Union[int, str]) -> SafeText:
    """
    Generate an individual page index link in a paginated list.
    
    This is a Django 6.0 compatible version of the jazzmin_paginator_number tag.
    The original version called format_html(html_str) without any format arguments,
    which raises a TypeError in Django 6.0. This version uses mark_safe instead
    since the HTML string is already formatted.
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

    # Use mark_safe instead of format_html(html_str) for Django 6.0 compatibility
    # format_html requires args or kwargs in Django 6.0, but html_str is already formatted
    return mark_safe(html_str)
