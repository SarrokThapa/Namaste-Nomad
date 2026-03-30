"""Validation and filtering utilities for package discovery."""

from ..services.search_service import filter_packages as filter_packages_service


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _apply_package_filters(request, queryset, forced_category=None, budget_threshold=None):
    return filter_packages_service(
        queryset,
        request.GET,
        forced_category=forced_category,
        budget_cutoff=budget_threshold,
    )

__all__ = [
    '_parse_int',
    '_parse_float',
    '_apply_package_filters',
]
