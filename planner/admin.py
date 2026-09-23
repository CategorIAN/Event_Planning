from django.contrib import admin

from .models import (
    Form,
    FormQuestion,
    FormQuestionChoice,
    FormQuestionGroup,
    FormRequest,
    FormSubmission,
    Hour,
    Person,
    Game,
    GameType,
    Platform,
    Day,
    FormQuestionGroupChoice,
    Duration
)


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "email",
        "status",
        "max_game_hours",
        "earliest_invite_lead",
        "latest_invite_lead",
        "event_cooldown",
    )
    list_filter = ("status",)
    search_fields = ("name", "email")
    ordering = ("name",)


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "google_form_id", "last_synced_at")
    search_fields = ("name", "google_form_id")
    ordering = ("name",)


@admin.register(Hour)
class HourAdmin(admin.ModelAdmin):
    list_display = ("id", "time")
    ordering = ("time",)


@admin.register(FormQuestionGroup)
class FormQuestionGroupAdmin(admin.ModelAdmin):
    list_display = ("id", "form", "name", "google_item_id")
    list_filter = ("form",)
    search_fields = ("name", "google_item_id", "form__name")
    ordering = ("form__name", "name")


@admin.register(FormQuestion)
class FormQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "form", "group", "name", "google_question_id", "hour")
    list_filter = ("form", "group", "hour")
    search_fields = ("name", "google_question_id", "form__name", "group__name")
    ordering = ("form__name", "group__name", "name")


@admin.register(FormQuestionChoice)
class FormQuestionChoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "question", "google_value", "value")
    list_filter = ("question__form",)
    search_fields = ("google_value", "value", "question__name")
    ordering = ("question__form__name", "question__name", "value")


@admin.register(FormRequest)
class FormRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "person", "form", "requested_at")
    list_filter = ("form",)
    search_fields = ("person__name", "person__email", "form__name")
    ordering = ("-requested_at",)


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "submitted_name",
        "submitted_email",
        "form",
        "person",
        "submitted_at",
        "google_response_id",
    )
    list_filter = ("form",)
    search_fields = (
        "submitted_name",
        "submitted_email",
        "google_response_id",
        "person__name",
        "person__email",
    )
    ordering = ("-submitted_at",)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("google_response_id",)
        return ()


@admin.register(GameType)
class GameTypeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "url",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "name",
    )


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "game_type", "url")
    list_filter = ("game_type",)
    search_fields = ("name", "game_type__name")
    ordering = ("name",)


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "url",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "name",
    )


@admin.register(Day)
class DayAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "order",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "order",
    )


@admin.register(FormQuestionGroupChoice)
class FormQuestionGroupChoiceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "group",
        "google_value",
        "day",
    )

    list_filter = (
        "group",
        "day",
    )

    search_fields = (
        "google_value",
        "group__name",
        "day__name",
    )

    ordering = (
        "group__name",
        "google_value",
    )


@admin.register(Duration)
class DurationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "days",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "days",
    )

