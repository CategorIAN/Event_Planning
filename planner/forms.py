from django import forms

from planner.models import Form, Person
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
