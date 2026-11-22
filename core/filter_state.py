"""Give each authenticated browser session an opaque, non-auth storage namespace."""
import uuid


def filter_state_context(request):
    if not getattr(request, 'plus_user', None) or not hasattr(request, 'session'):
        return {}
    user = request.plus_user
    owner = f"{getattr(user, 'gucode', '')}:{getattr(user, 'utitle', '')}"
    scope = request.session.get('filter_state_scope')
    if not scope or request.session.get('filter_state_owner') != owner:
        scope = uuid.uuid4().hex
        request.session['filter_state_scope'] = scope
        request.session['filter_state_owner'] = owner
    return {'filter_state_scope': scope}
