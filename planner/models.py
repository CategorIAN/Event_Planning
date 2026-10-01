from datetime import datetime, timedelta
from django.db import models
from django.utils import timezone


class Day(models.Model):
    name = models.CharField(max_length=20, unique=True)
    order = models.PositiveSmallIntegerField(unique=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class Hour(models.Model):
    time = models.TimeField(unique=True)

    class Meta:
        ordering = ["time"]

    def __str__(self):
        return self.time.strftime("%I:%M %p").lstrip("0")


class DayHour(models.Model):
    day = models.ForeignKey(
        Day,
        on_delete=models.CASCADE,
        related_name="day_hours",
    )
    hour = models.ForeignKey(
        Hour,
        on_delete=models.CASCADE,
        related_name="day_hours",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["day", "hour"],
                name="unique_day_hour",
            )
        ]
        ordering = ["day__order", "hour__time"]

    def __str__(self):
        return f"{self.day} at {self.hour}"


class TimeSpan(models.Model):
    """A half-open interval of availability slots on one day."""

    day = models.ForeignKey(
        Day,
        on_delete=models.CASCADE,
        related_name="time_spans",
    )
    start_hour = models.ForeignKey(
        Hour,
        on_delete=models.CASCADE,
        related_name="starting_time_spans",
    )
    end_hour = models.ForeignKey(
        Hour,
        on_delete=models.CASCADE,
        related_name="ending_time_spans",
    )
    day_hours = models.ManyToManyField(
        DayHour,
        related_name="time_spans",
    )

    @property
    def duration_hours(self):
        return self.end_hour.time.hour - self.start_hour.time.hour

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["day", "start_hour", "end_hour"],
                name="unique_time_span",
            )
        ]
        ordering = ["day__order", "start_hour__time", "end_hour__time"]

    def __str__(self):
        return f"{self.day} from {self.start_hour} to {self.end_hour}"

    @property
    def duration_hours(self) -> int:
        """The clock duration between the interval's hour boundaries."""
        start = datetime.combine(datetime.min.date(), self.start_hour.time)
        end = datetime.combine(datetime.min.date(), self.end_hour.time)
        return int((end - start).total_seconds() / 3600)


class Duration(models.Model):
    name = models.CharField(max_length=160)
    days = models.PositiveIntegerField()

    def __str__(self):
        return self.name


class GameType(models.Model):
    name = models.CharField(max_length=160, unique=True)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.name


class Game(models.Model):
    name = models.CharField(max_length=160, unique=True)
    url = models.URLField(blank=True)

    game_type = models.ForeignKey(
        GameType,
        on_delete=models.PROTECT,
        related_name="games",
    )

    expected_duration_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    min_players = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )
    max_players = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name


class Platform(models.Model):
    name = models.CharField(max_length=160, unique=True)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.name


class Person(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        NOT_NOW = "not_now", "Not Now"
        PLEASE_REMOVE = "please_remove", "Please Remove"

    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)

    max_game_hours = models.PositiveIntegerField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    earliest_invite_lead = models.DurationField(
        blank=True,
        null=True,
    )

    latest_invite_lead = models.DurationField(
        blank=True,
        null=True,
    )

    guest_games = models.TextField(
        blank=True,
    )

    event_cooldown = models.DurationField(
        default=timedelta(weeks=1),
        blank=True,
        null=True,
    )

    availability = models.ManyToManyField(
        DayHour,
        related_name="available_people",
        blank=True,
    )

    games = models.ManyToManyField(
        Game,
        related_name="interested_people",
        blank=True,
    )

    game_types = models.ManyToManyField(
        GameType,
        related_name="interested_people",
        blank=True,
    )

    platforms = models.ManyToManyField(
        Platform,
        related_name="people",
        blank=True,
    )

    def __str__(self):
        return self.name


class Form(models.Model):
    name = models.CharField(max_length=160)

    google_form_id = models.CharField(
        max_length=255,
        unique=True,
    )

    survey_url = models.URLField(blank=True)

    last_synced_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.name


class FormQuestionGroup(models.Model):
    form = models.ForeignKey(
        Form,
        on_delete=models.CASCADE,
        related_name="question_groups",
    )
    google_item_id = models.CharField(max_length=255)
    name = models.CharField(max_length=160)

    def __str__(self):
        return f"{self.form}: {self.name}"


class FormQuestion(models.Model):
    form = models.ForeignKey(
        Form,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    group = models.ForeignKey(
        FormQuestionGroup,
        on_delete=models.CASCADE,
        related_name="questions",
        blank=True,
        null=True,
    )
    google_question_id = models.CharField(
        max_length=255,
    )
    # Internal name used by the application, such as:
    # status, max_game_hours, event_cooldown
    name = models.CharField(
        max_length=160,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["form", "google_question_id"],
                name="unique_google_question_per_form",
            )
        ]

    def __str__(self):
        return f"{self.form}: {self.name}"

    hour = models.ForeignKey(
        "Hour",
        on_delete=models.SET_NULL,
        related_name="form_questions",
        blank=True,
        null=True,
    )


class FormQuestionChoice(models.Model):
    question = models.ForeignKey(
        FormQuestion,
        on_delete=models.CASCADE,
        related_name="choices",
    )

    # Exact value returned by Google Forms
    google_value = models.CharField(
        max_length=500,
    )

    # Internal application-friendly value
    value = models.CharField(
        max_length=160,
    )

    game = models.ForeignKey(
        Game,
        on_delete=models.SET_NULL,
        related_name="form_question_choices",
        blank=True,
        null=True,
    )

    platform = models.ForeignKey(
        Platform,
        on_delete=models.SET_NULL,
        related_name="form_question_choices",
        blank=True,
        null=True,
    )

    game_type = models.ForeignKey(
        GameType,
        on_delete=models.SET_NULL,
        related_name="form_question_choices",
        blank=True,
        null=True,
    )

    duration = models.ForeignKey(
        Duration,
        on_delete=models.SET_NULL,
        related_name="form_question_choices",
        blank=True,
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question", "google_value"],
                name="unique_google_value_per_question",
            )
        ]

    def __str__(self):
        return f"{self.google_value} → {self.value}"


class FormRequest(models.Model):
    person = models.ForeignKey(
        "Person",
        on_delete=models.CASCADE,
        related_name="form_requests",
    )

    form = models.ForeignKey(
        Form,
        on_delete=models.CASCADE,
        related_name="requests",
    )

    requested_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.person} → {self.form}"


class FormSubmission(models.Model):
    form = models.ForeignKey(
        Form,
        on_delete=models.CASCADE,
        related_name="submissions",
    )

    person = models.ForeignKey(
        "Person",
        on_delete=models.SET_NULL,
        related_name="form_submissions",
        blank=True,
        null=True,
    )

    google_response_id = models.CharField(
        max_length=255,
    )

    submitted_name = models.CharField(
        max_length=160,
        blank=True,
    )

    submitted_email = models.EmailField(
        blank=True,
    )

    submitted_at = models.DateTimeField()

    raw_response_data = models.JSONField(
        default=dict,
    )

    def __str__(self):
        return f"{self.form}: {self.submitted_name} ({self.submitted_at})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["form", "google_response_id", "submitted_at"],
                name="unique_form_submission_revision",
            )
        ]


class FormQuestionGroupChoice(models.Model):
    group = models.ForeignKey(
        FormQuestionGroup,
        on_delete=models.CASCADE,
        related_name="choices",
    )

    google_value = models.CharField(max_length=500)

    day = models.ForeignKey(
        Day,
        on_delete=models.SET_NULL,
        related_name="form_question_group_choices",
        blank=True,
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "google_value"],
                name="unique_google_value_per_question_group",
            )
        ]

    def __str__(self):
        return f"{self.google_value} → {self.day or '(unmapped)'}"


class Event(models.Model):
    timestamp = models.DateTimeField()

    time_span = models.ForeignKey(
        TimeSpan,
        on_delete=models.PROTECT,
        related_name="events",
    )

    game = models.ForeignKey(
        Game,
        on_delete=models.PROTECT,
        related_name="events",
    )

    happened = models.BooleanField(
        null=True,
        blank=True,
        default=None,
    )

    def __str__(self):
        timestamp = self.timestamp.strftime(
            "%A, %B %d, %Y at %I:%M %p"
        ).replace(" 0", " ")

        return f"{self.game} — {timestamp}"


class Invitation(models.Model):
    class Result(models.TextChoices):
        PENDING = "pending", "Pending"
        DECLINED = "declined", "Declined"
        ATTENDING = "attending", "Attending"
        ATTENDED = "attended", "Attended"
        FLAKED = "flaked", "Flaked"
        WAITING = "waiting", "Waiting"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="invitations",
    )
    invited_at = models.DateTimeField()
    plus_ones = models.PositiveSmallIntegerField(default=0)
    result = models.CharField(
        max_length=20,
        choices=Result.choices,
        default=Result.PENDING,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "person"],
                name="unique_person_event_invitation",
            )
        ]

    def __str__(self):
        return f"{self.person} — {self.event}"






