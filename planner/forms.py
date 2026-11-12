from django import forms
from typing import Any

from planner.models import Event, Form, Game, Person, TimeSpan
from planner.services.survey_request_emails import INITIAL, REMINDER, RENEWAL


class SendSurveyRequestForm(forms.Form):
    person = forms.ModelChoiceField(queryset=Person.objects.all(), widget=forms.HiddenInput)
    form = forms.ModelChoiceField(queryset=Form.objects.all(), widget=forms.HiddenInput)
    action_token = forms.CharField(widget=forms.HiddenInput)
    request_type = forms.ChoiceField(
        choices=(
            (INITIAL, "Initial survey"),
            (RENEWAL, "Survey renewal"),
            (REMINDER, "Survey reminder"),
        )
    )

    def clean_person(self) -> Person:
        """Validate that the selected person can receive a survey request.

        Returns:
            The validated Person instance.

        Raises:
            ValidationError: If the person asked to be removed.
        """
        person = self.cleaned_data["person"]
        if person.status == Person.Status.PLEASE_REMOVE:
            raise forms.ValidationError("Requests cannot be sent to this person.")
        return person


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ("game", "timestamp", "time_span", "leader", "happened")
        widgets = {
            "timestamp": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize ordered field querysets and a default leader for new events.

        Args:
            *args: Django ModelForm positional arguments.
            **kwargs: Django ModelForm keyword arguments.
        """
        super().__init__(*args, **kwargs)
        self.fields["game"].queryset = Game.objects.order_by("name")
        self.fields["leader"].queryset = Person.objects.order_by("name")
        self.fields["time_span"].queryset = TimeSpan.objects.select_related(
            "day", "start_hour", "end_hour"
        ).order_by("day__order", "start_hour__time", "end_hour__time")
        self.fields["timestamp"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance.pk is None and not self.is_bound:
            owner = Person.objects.filter(role=Person.Role.OWNER).order_by(
                "name", "pk"
            ).first()
            if owner is not None:
                self.initial["leader"] = owner.pk
