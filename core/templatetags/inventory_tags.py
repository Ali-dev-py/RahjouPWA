from django import template
from core.inventory import inventory_allowed

register = template.Library()


@register.simple_tag(takes_context=True)
def inventory_navigation_allowed(context):
    request = context.get('request')
    user = getattr(request, 'plus_user', None) if request else None
    return inventory_allowed(user or context.get('current_user'))
