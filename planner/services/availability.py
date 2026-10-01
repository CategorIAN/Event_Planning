"""Shared availability subset helpers."""

from collections.abc import Iterable

from planner.models import DayHour, TimeSpan


def is_available_for_time_span(
    available_day_hour_ids: set[int], time_span: TimeSpan
) -> bool:
    """Return whether all DayHours required by a TimeSpan are available."""
    required_day_hour_ids = {day_hour.pk for day_hour in time_span.day_hours.all()}
    return includes_required_day_hours(available_day_hour_ids, required_day_hour_ids)


def includes_required_day_hours(
    available_day_hour_ids: set[int], required_day_hour_ids: set[int]
) -> bool:
    """Return whether availability contains every required DayHour."""
    return required_day_hour_ids <= available_day_hour_ids


def day_hour_ids(day_hours: Iterable[DayHour]) -> set[int]:
    """Return primary keys for a prefetched availability relation."""
    return {day_hour.pk for day_hour in day_hours}
