from django.db import models


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

    event_cooldown = models.DurationField(
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.name


class Form(models.Model):
    name = models.CharField(max_length=160)

    google_form_id = models.CharField(
        max_length=255,
        unique=True,
    )

    last_synced_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.name


class FormQuestion(models.Model):
    form = models.ForeignKey(
        Form,
        on_delete=models.CASCADE,
        related_name="questions",
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

    requested_at = models.DateTimeField()

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
        unique=True,
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
