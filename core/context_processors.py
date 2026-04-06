from django.db.utils import OperationalError, ProgrammingError

from .services.site_settings import get_site_settings


def site_settings(request):
    try:
        return {'site_settings': get_site_settings()}
    except (OperationalError, ProgrammingError):
        return {}
