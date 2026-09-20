from django.contrib import admin

from .models import (
    Form,
    FormQuestion,
    FormQuestionChoice,
    FormRequest,
    FormSubmission,
    Person,
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


@admin.register(FormQuestion)
class FormQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "form", "name", "google_question_id")
    list_filter = ("form",)
    search_fields = ("name", "google_question_id", "form__name")
    ordering = ("form__name", "name")


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
