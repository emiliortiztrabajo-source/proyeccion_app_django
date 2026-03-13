from decimal import Decimal

from django import template
from django.utils.http import urlencode

register = template.Library()


@register.filter
def money_ar(value, decimals=2):
    if value is None:
        return "—"
    try:
        dec = int(decimals)
    except Exception:
        dec = 2
    rendered = f"{float(value):,.{dec}f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")


@register.filter
def money_compact_ar(value):
    if value is None:
        return "—"

    amount = abs(float(value))
    sign = "-" if float(value) < 0 else ""

    def fmt(number, decimals):
        rendered = f"{number:,.{decimals}f}"
        return rendered.replace(",", "X").replace(".", ",").replace("X", ".")

    if amount >= 1_000_000_000:
        return f"{sign}{fmt(amount / 1_000_000_000, 2)}MM"
    if amount >= 1_000_000:
        return f"{sign}{fmt(amount / 1_000_000, 2)}M"
    if amount >= 1_000:
        return f"{sign}{fmt(amount / 1_000, 1)}K"
    return f"{sign}{fmt(amount, 0)}"


@register.filter
def abs_value(value):
    if value is None:
        return None
    return abs(Decimal(value))


@register.simple_tag(takes_context=True)
def update_query(context, **kwargs):
    request = context.get("request")
    if request is None:
        return ""

    query = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()
