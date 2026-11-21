"""Authenticated visitor defaults shared by all assignment forms."""
from .income_report import guid, name_key
from .models import ViewAllvisitors


def is_visitor(user):
    return name_key(getattr(user, 'utitle', '')) == 'ویزیتور'


def resolve_visitor(user):
    """Return one active GUID match; never pick arbitrarily among namesakes."""
    name = name_key(getattr(user, 'uname', ''))
    if not is_visitor(user) or not name:
        return None
    matches = {}
    for row in ViewAllvisitors.objects.using('plus').all():
        if row.active is not False and name_key(row.vizitorname) == name and guid(row.gvisitorid):
            matches[guid(row.gvisitorid)] = row
    return next(iter(matches.values())) if len(matches) == 1 else None


def visitor_context(request):
    """Also available to render()-based views, not just TemplateViews."""
    return {'is_visitor_user': is_visitor(getattr(request, 'plus_user', None)),
            'automatic_visitor': getattr(request, 'automatic_visitor', None),
            'automatic_visitor_error': getattr(request, 'automatic_visitor_error', '')}
