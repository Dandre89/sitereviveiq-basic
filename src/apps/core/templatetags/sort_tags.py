from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_header(context, field, label, sort_param="sort", dir_param="dir"):
    """
    Renders a clickable column header link that toggles ?sort=<field>
    and ?dir=asc/desc, preserving every other query param already on
    the URL (filters, other tables' sort state, etc). Shows an up/down
    arrow when this column is the active sort. Pass sort_param/dir_param
    when multiple sortable tables share one page.
    """
    request = context["request"]
    current_sort = request.GET.get(sort_param, "")
    current_dir = request.GET.get(dir_param, "asc")

    params = request.GET.copy()
    if current_sort == field and current_dir == "asc":
        new_dir = "desc"
    else:
        new_dir = "asc"
    params[sort_param] = field
    params[dir_param] = new_dir

    is_active = current_sort == field
    arrow = ""
    if is_active:
        arrow = " &darr;" if current_dir == "desc" else " &uarr;"

    css_class = "sort-header sort-header-active" if is_active else "sort-header"
    return format_html(
        '<a href="?{}" class="{}">{}</a>',
        params.urlencode(),
        css_class,
        format_html("{}{}", label, mark_safe(arrow)),
    )
