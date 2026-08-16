from django import template

register = template.Library()

# Translation tables (Fastest method in Python)
EN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
EN_TO_AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

@register.filter(name="persian_digits")
def persian_digits(value):
    if value is None:
        return ""
    return str(value).translate(EN_TO_FA)

@register.filter(name="arabic_digits")
def arabic_digits(value):
    if value is None:
        return ""
    return str(value).translate(EN_TO_AR)