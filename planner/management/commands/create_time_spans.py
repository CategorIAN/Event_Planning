from django.core.management.base import BaseCommand, CommandError

from planner.models import Day, DayHour, Hour, TimeSpan


class Command(BaseCommand):
    help = "Create and configure all same-day TimeSpan records from DayHour data."

    def handle(self, *args, **options):
        days = list(Day.objects.order_by("order"))
        hours = list(Hour.objects.order_by("time"))
        created_count = 0
        existing_count = 0

        for day in days:
            day_hours_by_hour = {
                day_hour.hour_id: day_hour
                for day_hour in DayHour.objects.filter(day=day, hour__in=hours)
            }
            missing_hours = [hour for hour in hours if hour.pk not in day_hours_by_hour]
            if missing_hours:
                missing_times = ", ".join(str(hour) for hour in missing_hours)
                raise CommandError(
                    f"{day} is missing DayHour records for: {missing_times}. "
                    "Run create_day_hours first."
                )

            for start_index, start_hour in enumerate(hours[:-1]):
                for end_index in range(start_index + 1, len(hours)):
                    end_hour = hours[end_index]
                    time_span, created = TimeSpan.objects.get_or_create(
                        day=day,
                        start_hour=start_hour,
                        end_hour=end_hour,
                    )
                    time_span.day_hours.set(
                        day_hours_by_hour[hour.pk]
                        for hour in hours[start_index:end_index]
                    )
                    if created:
                        created_count += 1
                    else:
                        existing_count += 1

        total_processed = created_count + existing_count
        self.stdout.write(
            "\n".join(
                [
                    f"TimeSpans created: {created_count}",
                    f"TimeSpans already existing: {existing_count}",
                    f"Total TimeSpans processed: {total_processed}",
                ]
            )
        )
