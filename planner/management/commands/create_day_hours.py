from django.core.management.base import BaseCommand

from planner.models import Day, DayHour, Hour


class Command(BaseCommand):
    help = "Create missing DayHour records for every existing Day and Hour."

    def handle(self, *args, **options):
        days = list(Day.objects.all())
        hours = list(Hour.objects.all())
        created_count = 0
        existing_count = 0

        for day in days:
            for hour in hours:
                _, created = DayHour.objects.get_or_create(day=day, hour=hour)
                if created:
                    created_count += 1
                else:
                    existing_count += 1

        self.stdout.write(
            "\n".join(
                [
                    f"Day records: {len(days)}",
                    f"Hour records: {len(hours)}",
                    f"Possible DayHour combinations: {len(days) * len(hours)}",
                    f"DayHour records created: {created_count}",
                    f"DayHour records already existing: {existing_count}",
                ]
            )
        )
