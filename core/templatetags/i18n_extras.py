from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()

# Translation tables
EN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
EN_TO_AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


@register.filter(name="persian_digits")
def persian_digits(value):
    """Converts English digits to Persian digits."""
    if value is None:
        return ""
    return str(value).translate(EN_TO_FA)


@register.filter(name="arabic_digits")
def arabic_digits(value):
    """Converts English digits to Arabic digits."""
    if value is None:
        return ""
    return str(value).translate(EN_TO_AR)


@register.filter(name="persian_price")
def persian_price(value, persian_comma=False):
    """Formats numbers with thousand separators and converts them to Persian digits.

    Example: 1125500 -> ۱,۱۲۵,۵۰۰
    If persian_comma=True -> ۱،۱۲۵،۵۰۰
    """
    if value is None or value == "":
        return ""

    try:
        # Handles int, float, Decimal, or number strings safely
        d = Decimal(str(value))
        # Remove trailing zero decimals if it's a whole number
        formatted = f"{int(d):,}" if d % 1 == 0 else f"{d:,}"
    except (InvalidOperation, TypeError, ValueError):
        formatted = str(value)

    result = formatted.translate(EN_TO_FA)

    # Optional: replace Latin comma ',' with Persian comma '،'
    if persian_comma:
        result = result.replace(",", "،")

    return result