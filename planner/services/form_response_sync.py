"""Synchronization of configured Google Form responses into planner models."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from planner.models import (
    DayHour,
    Form,
    FormQuestion,
    FormQuestionChoice,
    FormQuestionGroup,
    FormQuestionGroupChoice,
    FormSubmission,
    Person,
)
from planner.services.google_forms import get_form_responses


GOOGLE_FORM_ID = "1N6QRk-OwsVANBopI11X9NOQTPcTyGP6K8Ql-ocXbayI"
SUBMITTED_NAME_QUESTION_ID = "397694e8"


class FormResponseSynchronizationError(Exception):
    """Raised when a response cannot be synchronized safely."""


def normalize_submitted_name(name: str) -> str:
    """Normalize a submitted name for storage and Person matching."""
    return " ".join(name.split()).title()


def synchronize_google_form_responses() -> dict[str, int]:
    """Synchronize new Google Form response revisions into the planner."""
    try:
        form = Form.objects.get(google_form_id=GOOGLE_FORM_ID)
    except Form.DoesNotExist as error:
        raise FormResponseSynchronizationError(
            f"No Form exists with Google Form ID {GOOGLE_FORM_ID}."
        ) from error

    latest_submitted_at = FormSubmission.objects.filter(form=form).aggregate(
        latest=Max("submitted_at")
    )["latest"]
    cutoff = latest_submitted_at or timezone.now() - timedelta(days=1)
    response_data = get_form_responses(form.google_form_id, submitted_after=cutoff)
    responses = response_data["responses"]
    ordered_responses = sorted(responses, key=_response_submitted_at)

    with transaction.atomic():
        new_submissions = []
        for response in ordered_responses:
            with transaction.atomic():
                submission, created = _store_submission(form, response)
                if created:
                    new_submissions.append(submission)

        for submission in sorted(new_submissions, key=lambda submission: submission.submitted_at):
            with transaction.atomic():
                _apply_submission_if_exact_person_match(submission)

    return {
        "responses_retrieved": len(responses),
        "submissions_created": len(new_submissions),
        "submissions_already_existing": len(responses) - len(new_submissions),
    }


def _store_submission(
    form: Form, response: dict[str, Any]
) -> tuple[FormSubmission, bool]:
    response_id = response.get("responseId")
    if not isinstance(response_id, str) or not response_id:
        raise FormResponseSynchronizationError("Google response is missing responseId.")

    submitted_at = _response_submitted_at(response)
    submitted_email = response.get("respondentEmail", "")
    if not isinstance(submitted_email, str):
        raise FormResponseSynchronizationError(
            f"Google response {response_id} has an invalid respondentEmail."
        )

    submitted_name = normalize_submitted_name(
        _single_answer_value(response, SUBMITTED_NAME_QUESTION_ID, "submitted name")
    )

    return FormSubmission.objects.get_or_create(
        form=form,
        google_response_id=response_id,
        submitted_at=submitted_at,
        defaults={
            "submitted_email": submitted_email,
            "submitted_name": submitted_name,
            "raw_response_data": response,
        },
    )


def apply_form_submission_to_person(
    submission: FormSubmission, person: Person
) -> None:
    """Assign a submission to a Person and apply its configured survey data."""
    submission.person = person
    submission.save(update_fields=["person"])

    form = submission.form

    person.status = _mapped_choice_value(submission, _form_question(form, "status")).value
    person.max_game_hours = _integer_answer(
        submission, _form_question(form, "max_hours")
    )
    person.earliest_invite_lead = _mapped_duration(
        submission, _form_question(form, "earliest_invite_lead")
    )
    person.latest_invite_lead = _mapped_duration(
        submission, _form_question(form, "latest_invite_lead")
    )
    person.guest_games = _single_answer_value(
        submission.raw_response_data,
        _form_question(form, "guest_games").google_question_id,
        "guest_games",
        allow_empty=True,
    )
    person.save()

    _set_mapped_many_to_many(person, submission, "games", "game")
    _set_mapped_many_to_many(person, submission, "game_types", "game_type")
    _set_mapped_many_to_many(person, submission, "platforms", "platform")
    _set_availability(person, submission)


def _apply_submission_if_exact_person_match(submission: FormSubmission) -> bool:
    person = _find_exact_person(submission)
    if person is None:
        return False
    apply_form_submission_to_person(submission, person)
    return True


def _find_exact_person(submission: FormSubmission) -> Person | None:
    people = list(
        Person.objects.filter(
            email=submission.submitted_email,
            name=submission.submitted_name,
        )
    )
    if len(people) == 1:
        return people[0]
    return None


def _form_question(form: Form, name: str) -> FormQuestion:
    try:
        return FormQuestion.objects.get(form=form, name=name)
    except FormQuestion.DoesNotExist as error:
        raise FormResponseSynchronizationError(
            f"Form '{form.name}' has no FormQuestion named '{name}'."
        ) from error
    except FormQuestion.MultipleObjectsReturned as error:
        raise FormResponseSynchronizationError(
            f"Form '{form.name}' has multiple FormQuestions named '{name}'."
        ) from error


def _mapped_choice_value(
    submission: FormSubmission, question: FormQuestion
) -> FormQuestionChoice:
    submitted_value = _single_answer_value(
        submission.raw_response_data, question.google_question_id, question.name
    )
    try:
        return FormQuestionChoice.objects.get(
            question=question, google_value=submitted_value
        )
    except FormQuestionChoice.DoesNotExist as error:
        raise FormResponseSynchronizationError(
            f"No choice mapping exists for '{submitted_value}' on '{question.name}'."
        ) from error


def _mapped_duration(submission: FormSubmission, question: FormQuestion) -> timedelta:
    choice = _mapped_choice_value(submission, question)
    if choice.duration is None:
        raise FormResponseSynchronizationError(
            f"Choice '{choice.google_value}' on '{question.name}' has no Duration mapping."
        )
    return timedelta(days=choice.duration.days)


def _integer_answer(submission: FormSubmission, question: FormQuestion) -> int:
    value = _single_answer_value(
        submission.raw_response_data, question.google_question_id, question.name
    )
    try:
        return int(value)
    except ValueError as error:
        raise FormResponseSynchronizationError(
            f"Answer '{value}' for '{question.name}' is not an integer."
        ) from error


def _set_mapped_many_to_many(
    person: Person, submission: FormSubmission, question_name: str, mapping_field: str
) -> None:
    question = _form_question(submission.form, question_name)
    selected_values = _answer_values(
        submission.raw_response_data, question.google_question_id
    )
    mapped_objects = []
    for value in selected_values:
        try:
            choice = FormQuestionChoice.objects.get(question=question, google_value=value)
        except FormQuestionChoice.DoesNotExist as error:
            raise FormResponseSynchronizationError(
                f"No choice mapping exists for '{value}' on '{question.name}'."
            ) from error
        mapped_object = getattr(choice, mapping_field)
        if mapped_object is None:
            raise FormResponseSynchronizationError(
                f"Choice '{value}' on '{question.name}' has no {mapping_field} mapping."
            )
        mapped_objects.append(mapped_object)

    getattr(person, question_name).set(mapped_objects)


def _set_availability(person: Person, submission: FormSubmission) -> None:
    try:
        group = FormQuestionGroup.objects.get(form=submission.form, name="availability")
    except FormQuestionGroup.DoesNotExist as error:
        raise FormResponseSynchronizationError(
            f"Form '{submission.form.name}' has no FormQuestionGroup named 'availability'."
        ) from error
    except FormQuestionGroup.MultipleObjectsReturned as error:
        raise FormResponseSynchronizationError(
            f"Form '{submission.form.name}' has multiple availability groups."
        ) from error

    day_hours = []
    for question in FormQuestion.objects.filter(group=group).select_related("hour"):
        if question.hour is None:
            raise FormResponseSynchronizationError(
                f"Availability question '{question.name}' has no Hour mapping."
            )
        for value in _answer_values(submission.raw_response_data, question.google_question_id):
            try:
                choice = FormQuestionGroupChoice.objects.select_related("day").get(
                    group=group, google_value=value
                )
            except FormQuestionGroupChoice.DoesNotExist as error:
                raise FormResponseSynchronizationError(
                    f"No availability mapping exists for '{value}'."
                ) from error
            if choice.day is None:
                raise FormResponseSynchronizationError(
                    f"Availability value '{value}' has no Day mapping."
                )
            try:
                day_hours.append(DayHour.objects.get(day=choice.day, hour=question.hour))
            except DayHour.DoesNotExist as error:
                raise FormResponseSynchronizationError(
                    f"DayHour is missing for {choice.day} at {question.hour}."
                ) from error

    person.availability.set(day_hours)


def _response_submitted_at(response: dict[str, Any]) -> datetime:
    timestamp = response.get("lastSubmittedTime")
    if not isinstance(timestamp, str):
        raise FormResponseSynchronizationError(
            "Google response is missing a valid lastSubmittedTime."
        )
    try:
        submitted_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise FormResponseSynchronizationError(
            f"Google response has an invalid lastSubmittedTime: {timestamp!r}."
        ) from error
    if submitted_at.tzinfo is None:
        raise FormResponseSynchronizationError(
            "Google response lastSubmittedTime must include timezone information."
        )
    return submitted_at.astimezone(datetime_timezone.utc)


def _single_answer_value(
    response: dict[str, Any], question_id: str, question_name: str, allow_empty: bool = False
) -> str:
    values = _answer_values(response, question_id)
    if not values and allow_empty:
        return ""
    if len(values) != 1:
        raise FormResponseSynchronizationError(
            f"Expected one answer for '{question_name}', found {len(values)}."
        )
    return values[0]


def _answer_values(response: dict[str, Any], question_id: str) -> list[str]:
    answers = response.get("answers", {})
    if not isinstance(answers, dict):
        raise FormResponseSynchronizationError("Google response has invalid answers data.")
    answer = answers.get(question_id)
    if answer is None:
        return []
    if not isinstance(answer, dict):
        raise FormResponseSynchronizationError(
            f"Google response has an invalid answer for question ID {question_id}."
        )
    text_answers = answer.get("textAnswers", {})
    if not isinstance(text_answers, dict):
        raise FormResponseSynchronizationError(
            f"Google response has invalid text answers for question ID {question_id}."
        )
    values = text_answers.get("answers", [])
    if not isinstance(values, list):
        raise FormResponseSynchronizationError(
            f"Google response has invalid answer values for question ID {question_id}."
        )
    result = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("value"), str):
            raise FormResponseSynchronizationError(
                f"Google response has an invalid answer value for question ID {question_id}."
            )
        result.append(value["value"])
    return result
