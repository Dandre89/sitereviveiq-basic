"""
Shared sort-param handling for list/table views. Every sortable table in
the app follows the same convention: ?sort=<friendly-key>&dir=asc|desc,
validated against a per-view whitelist so we never pass user input
straight into order_by().
"""


def resolve_sort(request, allowed_fields: dict, default_key: str, sort_param="sort", dir_param="dir"):
    """
    allowed_fields maps a friendly, URL-safe key (used in ?sort=) to the
    real ORM field path (or annotated alias) to order by. Returns
    (order_by_value, active_key, direction) — order_by_value already has
    the leading "-" applied for descending.

    sort_param/dir_param let multiple independently-sortable tables live
    on the same page (e.g. a website's Open issues, Pages, and Scan
    history tables) without clobbering each other's query params.
    """
    sort_key = request.GET.get(sort_param, default_key)
    if sort_key not in allowed_fields:
        sort_key = default_key

    direction = request.GET.get(dir_param, "asc")
    if direction not in ("asc", "desc"):
        direction = "asc"

    field = allowed_fields[sort_key]
    order_by_value = field if direction == "asc" else f"-{field}"
    return order_by_value, sort_key, direction
