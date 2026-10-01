from django import forms

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

    def clean_person(self):
        person = self.cleaned_data["person"]
        if person.status == Person.Status.PLEASE_REMOVE:
            raise forms.ValidationError("Requests cannot be sent to this person.")
        return person


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ("game", "timestamp", "time_span", "happened")
        widgets = {
            "timestamp": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["game"].queryset = Game.objects.order_by("name")
        self.fields["time_span"].queryset = TimeSpan.objects.select_related(
            "day", "start_hour", "end_hour"
        ).order_by("day__order", "start_hour__time", "end_hour__time")
        self.fields["timestamp"].input_formats = ["%Y-%m-%dT%H:%M"]
