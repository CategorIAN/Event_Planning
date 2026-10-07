import base64
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from email import message_from_bytes
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.db import DatabaseError

from planner.forms import EventForm
from planner.models import (
    Day,
    DayHour,
    Event,
    Form,
    FormRequest,
    FormSubmission,
    Game,
    GameType,
    Hour,
    Person,
    TimeSpan,
    Invitation,
)
from planner.services.invitation_list import get_invitation_list
from planner.services.event_invitations import (
    EventInvitationAlreadyExistsError,
    EventInvitationIneligibleError,
    build_event_invitation_email,
    get_current_attendance,
    send_event_invitation,
)
from planner.services.survey_updates import (
    AWAITING_RESPONSE,
    CURRENT,
    INITIAL_REQUEST_DUE,
    REMINDER_DUE,
    RENEWAL_DUE,
    add_calendar_months,
    calculate_survey_update_schedule,
    default_request_type_for_status,
)
from planner.services.gmail import send_email
from planner.services.gmail import GmailSendError
from planner.services.survey_request_emails import (
    INITIAL,
    REMINDER,
    RENEWAL,
    SurveyRequestSendError,
    SurveyRequestRecordingError,
    SurveyRequestValidationError,
    SurveyEmail,
    SurveyRequestResult,
    build_survey_request_email,
    request_survey_email,
)


def aware(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=datetime_timezone.utc)


class SurveyUpdateScheduleTests(TestCase):
    def test_initial_request_is_due_now(self):
        now = aware(2026, 9, 29)
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.ACTIVE,
            last_requested_at=None,
            last_submitted_at=None,
            now=now,
        )
        self.assertEqual(schedule.status, INITIAL_REQUEST_DUE)
        self.assertEqual(schedule.next_contact_due, now)

    def test_active_renewal_is_due_after_six_calendar_months(self):
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.ACTIVE,
            last_requested_at=None,
            last_submitted_at=aware(2026, 3, 28),
            now=aware(2026, 9, 29),
        )
        self.assertEqual(schedule.status, RENEWAL_DUE)

    def test_not_now_renewal_is_due_after_three_calendar_months(self):
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.NOT_NOW,
            last_requested_at=None,
            last_submitted_at=aware(2026, 3, 28),
            now=aware(2026, 6, 29),
        )
        self.assertEqual(schedule.status, RENEWAL_DUE)

    def test_reminder_is_due_after_one_calendar_month(self):
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.ACTIVE,
            last_requested_at=aware(2026, 8, 28),
            last_submitted_at=None,
            now=aware(2026, 9, 29),
        )
        self.assertEqual(schedule.status, REMINDER_DUE)

    def test_new_request_restarts_reminder_interval(self):
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.ACTIVE,
            last_requested_at=aware(2026, 9, 20),
            last_submitted_at=None,
            now=aware(2026, 9, 29),
        )
        self.assertEqual(schedule.status, AWAITING_RESPONSE)
        self.assertEqual(schedule.next_contact_due, aware(2026, 10, 20))

    def test_submission_at_same_time_as_request_answers_it(self):
        submitted_at = aware(2026, 9, 28)
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.ACTIVE,
            last_requested_at=submitted_at,
            last_submitted_at=submitted_at,
            now=aware(2026, 9, 29),
        )
        self.assertEqual(schedule.status, CURRENT)

    def test_calendar_month_boundaries_and_strict_overdue_comparison(self):
        self.assertEqual(add_calendar_months(aware(2026, 1, 31), 1), aware(2026, 2, 28))
        schedule = calculate_survey_update_schedule(
            person_status=Person.Status.ACTIVE,
            last_requested_at=aware(2026, 1, 31),
            last_submitted_at=None,
            now=aware(2026, 2, 28),
        )
        self.assertEqual(schedule.status, AWAITING_RESPONSE)


@override_settings(GENERAL_SURVEY_FORM_ID="general-survey")
class SurveyUpdatesViewTests(TestCase):
    def setUp(self):
        self.general_form = Form.objects.create(
            name="General Survey",
            google_form_id="general-survey",
            survey_url="https://example.com/general-survey",
        )
        self.other_form = Form.objects.create(name="Other Survey", google_form_id="other")
        self.person = Person.objects.create(name="Active Person", email="active@example.com")
        self.removed_person = Person.objects.create(
            name="Removed Person",
            email="removed@example.com",
            status=Person.Status.PLEASE_REMOVE,
        )

    def test_other_form_requests_and_submissions_do_not_affect_selected_form(self):
        FormRequest.objects.create(
            person=self.person,
            form=self.other_form,
            requested_at=aware(2026, 9, 1),
        )
        FormSubmission.objects.create(
            person=self.person,
            form=self.other_form,
            google_response_id="other-response",
            submitted_at=aware(2026, 9, 2),
            raw_response_data={},
        )

        response = self.client.get(reverse("survey_updates"))

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual(rows, [self.person])
        self.assertIsNone(rows[0].last_requested_at)
        self.assertIsNone(rows[0].last_submitted_at)
        self.assertEqual(rows[0].schedule.status, INITIAL_REQUEST_DUE)

    def test_request_count_and_row_highlighting_use_requests_after_submission(self):
        FormSubmission.objects.create(
            person=self.person,
            form=self.general_form,
            google_response_id="active-response",
            submitted_at=aware(2026, 1, 1),
            raw_response_data={},
        )
        for day in (2, 3):
            FormRequest.objects.create(
                person=self.person,
                form=self.general_form,
                requested_at=aware(2026, 1, day),
            )

        second_person = Person.objects.create(
            name="Three Requests", email="three@example.com"
        )
        FormSubmission.objects.create(
            person=second_person,
            form=self.general_form,
            google_response_id="three-response",
            submitted_at=aware(2026, 1, 1),
            raw_response_data={},
        )
        for day in (2, 3, 4):
            FormRequest.objects.create(
                person=second_person,
                form=self.general_form,
                requested_at=aware(2026, 1, day),
            )

        response = self.client.get(reverse("survey_updates"))
        rows = {person.pk: person for person in response.context["rows"]}

        self.assertEqual(rows[self.person.pk].request_count, 2)
        self.assertEqual(rows[second_person.pk].request_count, 3)
        self.assertContains(response, 'class="request-count-warning"')
        self.assertContains(response, 'class="request-count-danger"')

    def _request_payload(self, *, due_only=False, request_type=INITIAL):
        query = "?"
        if due_only:
            query += "due_only=1"
        response = self.client.get(f"{reverse('survey_updates')}{query}")
        request_form = response.context["rows"][0].request_form
        return {
            "person": self.person.pk,
            "form": self.general_form.pk,
            "action_token": request_form["action_token"].value(),
            "request_type": request_type,
            "due_only": "1" if due_only else "",
        }

    def test_default_request_type_mappings(self):
        self.assertEqual(default_request_type_for_status(INITIAL_REQUEST_DUE), INITIAL)
        self.assertEqual(default_request_type_for_status(RENEWAL_DUE), RENEWAL)
        self.assertEqual(default_request_type_for_status(REMINDER_DUE), REMINDER)
        self.assertEqual(default_request_type_for_status(AWAITING_RESPONSE), REMINDER)
        self.assertEqual(default_request_type_for_status(CURRENT), RENEWAL)

        response = self.client.get(reverse("survey_updates"))
        self.assertContains(response, 'value="initial" selected')

    @patch("planner.views.request_survey_email")
    def test_valid_post_sends_selected_type_once_and_preserves_filter(self, mocked_send):
        def send_and_record(person, form, request_type):
            FormRequest.objects.create(person=person, form=form)
            return SurveyRequestResult(
                email=SurveyEmail(person.email, "Manual override", "Actual sent body"),
                message_id="gmail-message-id",
            )

        mocked_send.side_effect = send_and_record
        response = self.client.post(
            reverse("mark_survey_requested"),
            self._request_payload(due_only=True, request_type=REMINDER),
        )

        self.assertRedirects(
            response,
            "/survey-updates/?due_only=1",
            fetch_redirect_response=False,
        )
        self.assertEqual(FormRequest.objects.count(), 1)
        mocked_send.assert_called_once_with(self.person, self.general_form, REMINDER)

        response = self.client.get(response.url)
        self.assertEqual(response.context["email_confirmation"]["subject"], "Manual override")
        self.assertEqual(response.context["email_confirmation"]["body"], "Actual sent body")

    @patch("planner.views.request_survey_email")
    def test_failed_send_does_not_create_request_or_confirmation(self, mocked_send):
        mocked_send.side_effect = SurveyRequestSendError("Gmail unavailable")
        response = self.client.post(
            reverse("mark_survey_requested"),
            self._request_payload(request_type=INITIAL),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(FormRequest.objects.exists())
        response = self.client.get(response.url)
        self.assertIsNone(response.context["email_confirmation"])

    @patch("planner.views.request_survey_email")
    def test_recording_failure_shows_sent_email_without_creating_request(
        self, mocked_send
    ):
        sent_email = SurveyEmail(self.person.email, "Sent subject", "Sent body")
        mocked_send.side_effect = SurveyRequestRecordingError(
            "The email was sent but could not be recorded.",
            email=sent_email,
            message_id="gmail-message-id",
        )

        response = self.client.post(
            reverse("mark_survey_requested"), self._request_payload()
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(FormRequest.objects.exists())
        response = self.client.get(response.url)
        confirmation = response.context["email_confirmation"]
        self.assertFalse(confirmation["recorded"])
        self.assertEqual(confirmation["subject"], "Sent subject")

    def test_invalid_request_type_does_not_send_or_create_request(self):
        payload = self._request_payload()
        payload["request_type"] = "invalid"
        response = self.client.post(reverse("mark_survey_requested"), payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(FormRequest.objects.exists())

    def test_please_remove_person_cannot_create_request(self):
        response = self.client.get(reverse("survey_updates"))
        # Please Remove people are not rendered, and a forged POST is rejected too.
        payload = {
            "person": self.removed_person.pk,
            "form": self.general_form.pk,
            "action_token": "forged",
            "request_type": INITIAL,
        }
        response = self.client.post(reverse("mark_survey_requested"), payload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FormRequest.objects.exists())


class GmailServiceTests(TestCase):
    @patch("planner.services.gmail.get_gmail_service")
    def test_send_email_uses_urlsafe_base64_mime_message(self, get_gmail_service):
        service = MagicMock()
        get_gmail_service.return_value = service
        service.users().messages().send().execute.return_value = {"id": "gmail-message-id"}

        message_id = send_email(
            "person@example.com",
            "Survey request",
            "Please complete your survey.",
        )

        self.assertEqual(message_id, "gmail-message-id")
        send_arguments = service.users().messages().send.call_args.kwargs
        self.assertEqual(send_arguments["userId"], "me")
        raw_message = send_arguments["body"]["raw"]
        decoded_message = message_from_bytes(base64.urlsafe_b64decode(raw_message))
        self.assertEqual(decoded_message["To"], "person@example.com")
        self.assertEqual(decoded_message["Subject"], "Survey request")
        self.assertIn("Please complete your survey.", decoded_message.get_payload())


class SurveyRequestEmailTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(
            name="Ian Kessler", email="ian@example.com"
        )
        self.form = Form.objects.create(
            name="General Survey",
            google_form_id="survey-form",
            survey_url="https://example.com/general-survey",
        )

    def test_all_email_templates(self):
        initial = build_survey_request_email(self.person, self.form, INITIAL)
        renewal = build_survey_request_email(self.person, self.form, RENEWAL)
        reminder = build_survey_request_email(self.person, self.form, REMINDER)

        self.assertEqual(
            initial.subject,
            "Complete the survey to be considered for tabletop gaming events",
        )
        self.assertIn("availability, game interests, and preferences", initial.body)
        self.assertEqual(renewal.subject, "Please update your tabletop gaming survey")
        self.assertIn("even if your availability", renewal.body)
        self.assertEqual(
            reminder.subject,
            "Reminder: please complete your tabletop gaming survey",
        )
        self.assertIn("I may remove you from the invitation list", reminder.body)
        self.assertIn(self.form.survey_url, reminder.body)

    def test_validation_failures(self):
        self.person.email = ""
        with self.assertRaises(SurveyRequestValidationError):
            build_survey_request_email(self.person, self.form, INITIAL)

        self.person.email = "ian@example.com"
        self.person.status = Person.Status.PLEASE_REMOVE
        with self.assertRaises(SurveyRequestValidationError):
            build_survey_request_email(self.person, self.form, INITIAL)

        self.person.status = Person.Status.ACTIVE
        self.form.survey_url = "not a URL"
        with self.assertRaises(SurveyRequestValidationError):
            build_survey_request_email(self.person, self.form, INITIAL)

    @patch("planner.services.survey_request_emails.send_email")
    def test_successful_send_records_form_request(self, mocked_send_email):
        mocked_send_email.return_value = "gmail-message-id"

        result = request_survey_email(self.person, self.form, RENEWAL)

        self.assertEqual(result.message_id, "gmail-message-id")
        self.assertEqual(FormRequest.objects.filter(person=self.person, form=self.form).count(), 1)
        mocked_send_email.assert_called_once_with(
            self.person.email,
            "Please update your tabletop gaming survey",
            result.email.body,
        )

    @patch("planner.services.survey_request_emails.send_email")
    def test_failed_send_does_not_record_form_request(self, mocked_send_email):
        mocked_send_email.side_effect = GmailSendError("Gmail failed")

        with self.assertRaises(SurveyRequestSendError):
            request_survey_email(self.person, self.form, REMINDER)

        self.assertFalse(FormRequest.objects.exists())

    @patch("planner.services.survey_request_emails.FormRequest.objects.create")
    @patch("planner.services.survey_request_emails.send_email")
    def test_recording_failure_reports_sent_email_without_resending(
        self, mocked_send_email, mocked_create
    ):
        mocked_send_email.return_value = "gmail-message-id"
        mocked_create.side_effect = DatabaseError("database unavailable")

        with self.assertRaises(SurveyRequestRecordingError) as error:
            request_survey_email(self.person, self.form, INITIAL)

        self.assertIn("email was sent successfully", str(error.exception))
        mocked_send_email.assert_called_once()
        self.assertFalse(FormRequest.objects.exists())

    @patch("planner.services.survey_request_emails.send_email")
    def test_dry_run_does_not_send_or_record(self, mocked_send_email):
        result = request_survey_email(self.person, self.form, INITIAL, dry_run=True)

        self.assertIsNone(result.message_id)
        self.assertEqual(result.email.recipient, self.person.email)
        mocked_send_email.assert_not_called()
        self.assertFalse(FormRequest.objects.exists())


class CreateTimeSpansCommandTests(TestCase):
    def setUp(self):
        self.day = Day.objects.create(name="Saturday", order=6)
        self.hours = [
            Hour.objects.create(time=time(hour, 0)) for hour in (16, 17, 18, 19)
        ]
        for hour_record in self.hours:
            DayHour.objects.create(day=self.day, hour=hour_record)

    def test_creates_half_open_spans_and_repairs_existing_relationships(self):
        call_command("create_time_spans")

        self.assertEqual(TimeSpan.objects.count(), 6)
        span = TimeSpan.objects.get(
            day=self.day,
            start_hour=self.hours[0],
            end_hour=self.hours[3],
        )
        self.assertEqual(
            list(span.day_hours.order_by("hour__time").values_list("hour__time", flat=True)),
            [time(16, 0), time(17, 0), time(18, 0)],
        )

        span.day_hours.clear()
        call_command("create_time_spans")

        self.assertEqual(TimeSpan.objects.count(), 6)
        span.refresh_from_db()
        self.assertEqual(span.day_hours.count(), 3)


class AvailabilityViewTests(TestCase):
    def setUp(self):
        self.monday = Day.objects.create(name="Monday", order=1)
        self.wednesday = Day.objects.create(name="Wednesday", order=3)
        self.saturday = Day.objects.create(name="Saturday", order=6)
        self.hours = [
            Hour.objects.create(time=time(hour, 0)) for hour in (16, 17, 18, 19)
        ]
        for day in (self.monday, self.wednesday, self.saturday):
            for hour_record in self.hours:
                DayHour.objects.create(day=day, hour=hour_record)
        call_command("create_time_spans")

        game_type = GameType.objects.create(name="Board Game")
        self.game = Game.objects.create(
            name="Catan",
            game_type=game_type,
            expected_duration_hours=2,
            min_players=1,
        )
        Game.objects.create(name="No Duration", game_type=game_type)

        fully_available = Person.objects.create(name="Full", email="full@example.com")
        fully_available.games.add(self.game)
        fully_available.availability.add(
            DayHour.objects.get(day=self.saturday, hour=self.hours[0]),
            DayHour.objects.get(day=self.saturday, hour=self.hours[1]),
        )

        partially_available = Person.objects.create(
            name="Partial", email="partial@example.com"
        )
        partially_available.games.add(self.game)
        partially_available.availability.add(
            DayHour.objects.get(day=self.saturday, hour=self.hours[0])
        )

        monday_available = Person.objects.create(
            name="Monday", email="monday@example.com"
        )
        monday_available.games.add(self.game)
        monday_available.availability.add(
            DayHour.objects.get(day=self.monday, hour=self.hours[0]),
            DayHour.objects.get(day=self.monday, hour=self.hours[1]),
        )

        second_saturday_person = Person.objects.create(
            name="Second Saturday", email="second-saturday@example.com"
        )
        second_saturday_person.games.add(self.game)
        second_saturday_person.availability.add(
            DayHour.objects.get(day=self.saturday, hour=self.hours[0]),
            DayHour.objects.get(day=self.saturday, hour=self.hours[1]),
        )

    def test_counts_only_people_available_for_entire_valid_time_span(self):
        response = self.client.get(reverse("availability"))

        self.assertEqual(response.status_code, 200)
        game_grids = response.context["game_grids"]
        self.assertEqual(len(game_grids), 1)
        self.assertEqual(game_grids[0]["game"], self.game)
        self.assertEqual([row["hour"] for row in game_grids[0]["rows"]], [self.hours[0]])
        cells = game_grids[0]["rows"][0]["cells"]
        self.assertEqual([cell["count"] for cell in cells], [1, 0, 2])
        self.assertEqual(
            [cell["css_class"] for cell in cells],
            ["availability-valid", "availability-low", "availability-best"],
        )
        self.assertEqual([person["name"] for person in cells[0]["people"]], ["Monday"])
        self.assertEqual(cells[1]["people"], [])

        span = TimeSpan.objects.get(
            day=self.saturday,
            start_hour=self.hours[0],
            end_hour=self.hours[2],
        )
        self.assertEqual(span.duration_hours, 2)
        self.assertEqual(span.day_hours.count(), 2)


class InvitationListServiceTests(TestCase):
    def setUp(self):
        self.now = aware(2026, 10, 1)
        self.day = Day.objects.create(name="Saturday", order=6)
        self.start_hour = Hour.objects.create(time=time(16, 0))
        self.end_hour = Hour.objects.create(time=time(18, 0))
        self.required_day_hours = [
            DayHour.objects.create(day=self.day, hour=self.start_hour),
            DayHour.objects.create(day=self.day, hour=Hour.objects.create(time=time(17, 0))),
        ]
        self.time_span = TimeSpan.objects.create(
            day=self.day,
            start_hour=self.start_hour,
            end_hour=self.end_hour,
        )
        self.time_span.day_hours.set(self.required_day_hours)
        game_type = GameType.objects.create(name="Board Game")
        self.game = Game.objects.create(name="Catan", game_type=game_type)
        self.owner = Person.objects.create(
            name="Owner", email="owner@example.com", role=Person.Role.OWNER
        )
        self.leader = Person.objects.create(
            name="Leader", email="leader@example.com"
        )
        self.owner.games.add(self.game)
        self.owner.availability.add(*self.required_day_hours)
        self.leader.games.add(self.game)
        self.leader.availability.add(*self.required_day_hours)
        self.event = Event.objects.create(
            game=self.game,
            time_span=self.time_span,
            timestamp=self.now + timedelta(days=7),
            leader=self.leader,
        )
        self.new_person = self._eligible_person("New Person")

        self.attending_person = self._eligible_person("Attending Person")
        past_event = Event.objects.create(
            game=self.game,
            time_span=self.time_span,
            timestamp=self.now - timedelta(days=30),
            leader=self.owner,
        )
        Invitation.objects.create(
            event=past_event,
            person=self.attending_person,
            invited_at=self.now - timedelta(days=20),
            result=Invitation.Result.ATTENDED,
        )

        self.redeem_person = self._eligible_person("Redeem Person")
        Invitation.objects.create(
            event=self.event,
            person=self.redeem_person,
            invited_at=self.now - timedelta(days=1),
            result=Invitation.Result.WAITING,
        )

        self.recently_invited_person = self._eligible_person("Recent Invite")
        Invitation.objects.create(
            event=past_event,
            person=self.recently_invited_person,
            invited_at=self.now - timedelta(days=1),
            result=Invitation.Result.PENDING,
        )

        self.not_due_for_selected_event = self._eligible_person("Not Due Yet")
        self.not_due_for_selected_event.event_cooldown = timedelta(days=10)
        self.not_due_for_selected_event.save(update_fields=["event_cooldown"])
        recent_attendance_event = Event.objects.create(
            game=self.game,
            time_span=self.time_span,
            timestamp=self.now,
            leader=self.owner,
        )
        Invitation.objects.create(
            event=recent_attendance_event,
            person=self.not_due_for_selected_event,
            invited_at=self.now - timedelta(days=1),
            result=Invitation.Result.ATTENDED,
        )

        unavailable_person = Person.objects.create(
            name="Unavailable Person", email="unavailable@example.com"
        )
        unavailable_person.games.add(self.game)
        unavailable_person.availability.add(self.required_day_hours[0])

        self.not_now_person = self._eligible_person("Not Now Person")
        self.not_now_person.status = Person.Status.NOT_NOW
        self.not_now_person.save(update_fields=["status"])

    def _eligible_person(self, name):
        person = Person.objects.create(name=name, email=f"{name.lower().replace(' ', '')}@example.com")
        person.games.add(self.game)
        person.availability.add(*self.required_day_hours)
        return person

    def test_builds_and_orders_derived_invitation_rows(self):
        rows = get_invitation_list(self.event)
        rows_by_name = {row.person.name: row for row in rows}

        self.assertEqual(
            [row.person.name for row in rows],
            ["New Person", "Attending Person", "Recent Invite", "Redeem Person"],
        )
        self.assertNotIn("Unavailable Person", rows_by_name)
        self.assertNotIn("Not Due Yet", rows_by_name)
        self.assertNotIn("Not Now Person", rows_by_name)
        self.assertNotIn("Owner", rows_by_name)
        self.assertNotIn("Leader", rows_by_name)

        new_row = rows_by_name["New Person"]
        self.assertTrue(new_row.new)
        self.assertFalse(new_row.invited)

        self.assertFalse(rows_by_name["Recent Invite"].new)

        attending_row = rows_by_name["Attending Person"]
        self.assertEqual(
            attending_row.expected_attendance,
            self.now - timedelta(days=23),
        )

        redeem_row = rows_by_name["Redeem Person"]
        self.assertTrue(redeem_row.redeem)
        self.assertTrue(redeem_row.invited)
        self.assertEqual(redeem_row.expected_invite, self.now + timedelta(days=6))

    def test_events_page_displays_selected_event_and_invitation_list(self):
        response = self.client.get(reverse("events"), {"event_id": self.event.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_event"], self.event)
        self.assertContains(response, "Invitation List")
        self.assertContains(response, "New Person")
        self.assertNotContains(response, "Completed Survey")
        self.assertContains(response, "Leader")

    def test_event_form_defaults_to_owner_but_preserves_existing_leader(self):
        new_event_form = EventForm()
        existing_event_form = EventForm(instance=self.event)

        self.assertEqual(new_event_form["leader"].value(), self.owner.pk)
        self.assertEqual(existing_event_form["leader"].value(), self.leader.pk)

    def test_create_event_post_creates_and_selects_event(self):
        response = self.client.post(
            reverse("create_event"),
            {
                "game": self.game.pk,
                "time_span": self.time_span.pk,
                "leader": self.leader.pk,
                "timestamp": "2026-10-15T16:00",
                "happened": "",
            },
        )

        created_event = Event.objects.get(timestamp=aware(2026, 10, 15, 16))
        self.assertRedirects(response, f"/events/?event_id={created_event.pk}")
        self.assertEqual(created_event.game, self.game)
        self.assertEqual(created_event.time_span, self.time_span)
        self.assertEqual(created_event.leader, self.leader)

    @patch("planner.views.send_event_invitation")
    def test_events_page_invite_action_uses_event_invitation_service(self, mocked_send):
        mocked_send.return_value.message_id = "gmail-message-id"

        response = self.client.post(
            reverse(
                "send_event_invitation_from_events",
                args=[self.event.pk, self.new_person.pk],
            )
        )

        self.assertRedirects(response, f"/events/?event_id={self.event.pk}")
        mocked_send.assert_called_once_with(self.event, self.new_person)

    def _create_board_invitation(self, name, result, plus_ones=0):
        person = Person.objects.create(
            name=name,
            email=f"{name.lower().replace(' ', '')}@example.com",
        )
        return Invitation.objects.create(
            event=self.event,
            person=person,
            invited_at=aware(2026, 10, 1),
            result=result,
            plus_ones=plus_ones,
        )

    def test_active_invitations_board_has_all_results_and_only_selected_event(self):
        board_invitations = {
            value: self._create_board_invitation(label, value)
            for value, label in Invitation.Result.choices
        }
        other_event = Event.objects.create(
            game=self.game,
            time_span=self.time_span,
            timestamp=self.now + timedelta(days=8),
            leader=self.leader,
        )
        other_person = Person.objects.create(
            name="Other Event Person", email="other-event@example.com"
        )
        Invitation.objects.create(
            event=other_event,
            person=other_person,
            invited_at=aware(2026, 10, 1),
            result=Invitation.Result.PENDING,
        )

        response = self.client.get(reverse("events"), {"event_id": self.event.pk})
        columns = {column["value"]: column for column in response.context["invitation_columns"]}

        self.assertEqual(set(columns), set(Invitation.Result.values))
        for value, label in Invitation.Result.choices:
            self.assertContains(response, label)
            invitation = board_invitations[value]
            self.assertIn(invitation, columns[value]["invitations"])
        self.assertNotIn(
            other_person,
            [
                invitation
                for column in columns.values()
                for invitation in column["invitations"]
            ],
        )

    def test_invitation_result_update_validates_event_and_result(self):
        invitation = self._create_board_invitation("Pending Person", Invitation.Result.PENDING)

        response = self.client.post(
            reverse(
                "update_event_invitation_result",
                args=[self.event.pk, invitation.pk],
            ),
            {"result": Invitation.Result.ATTENDING},
        )
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.result, Invitation.Result.ATTENDING)

        response = self.client.post(
            reverse(
                "update_event_invitation_result",
                args=[self.event.pk, invitation.pk],
            ),
            {"result": "invalid"},
        )
        self.assertEqual(response.status_code, 400)
        invitation.refresh_from_db()
        self.assertEqual(invitation.result, Invitation.Result.ATTENDING)

        other_event = Event.objects.create(
            game=self.game,
            time_span=self.time_span,
            timestamp=self.now + timedelta(days=8),
            leader=self.leader,
        )
        other_invitation = Invitation.objects.create(
            event=other_event,
            person=Person.objects.create(name="Other", email="other@example.com"),
            invited_at=aware(2026, 10, 1),
            result=Invitation.Result.PENDING,
        )
        response = self.client.post(
            reverse(
                "update_event_invitation_result",
                args=[self.event.pk, other_invitation.pk],
            ),
            {"result": Invitation.Result.ATTENDING},
        )
        self.assertEqual(response.status_code, 400)
        other_invitation.refresh_from_db()
        self.assertEqual(other_invitation.result, Invitation.Result.PENDING)

    def test_plus_one_updates_persist_and_cannot_go_below_zero(self):
        invitation = self._create_board_invitation("Plus One Person", Invitation.Result.PENDING)
        update_url = reverse(
            "update_event_invitation_plus_ones",
            args=[self.event.pk, invitation.pk],
        )

        response = self.client.post(update_url, {"delta": 1})
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.plus_ones, 1)

        response = self.client.post(update_url, {"delta": -1})
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.plus_ones, 0)

        response = self.client.post(update_url, {"delta": -1})
        self.assertEqual(response.status_code, 400)
        invitation.refresh_from_db()
        self.assertEqual(invitation.plus_ones, 0)


class EventInvitationServiceTests(TestCase):
    def setUp(self):
        self.day = Day.objects.create(name="Saturday", order=6)
        self.start_hour = Hour.objects.create(time=time(16, 0))
        self.end_hour = Hour.objects.create(time=time(18, 0))
        self.required_day_hours = [
            DayHour.objects.create(day=self.day, hour=self.start_hour),
            DayHour.objects.create(
                day=self.day,
                hour=Hour.objects.create(time=time(17, 0)),
            ),
        ]
        self.time_span = TimeSpan.objects.create(
            day=self.day,
            start_hour=self.start_hour,
            end_hour=self.end_hour,
        )
        self.time_span.day_hours.set(self.required_day_hours)
        game_type = GameType.objects.create(name="Board Game")
        self.game = Game.objects.create(
            name="Catan",
            game_type=game_type,
            max_players=6,
            boardgamegeek_url="https://boardgamegeek.com/boardgame/13/catan",
        )
        self.leader = Person.objects.create(
            name="Leader",
            email="leader@example.com",
            role=Person.Role.OWNER,
        )
        self.event = Event.objects.create(
            game=self.game,
            time_span=self.time_span,
            timestamp=aware(2026, 10, 17, 16),
            leader=self.leader,
        )
        self.recipient = self._eligible_person("Recipient")
        self.attending_person = self._eligible_person("Attending")
        Invitation.objects.create(
            event=self.event,
            person=self.attending_person,
            invited_at=aware(2026, 10, 1),
            result=Invitation.Result.ATTENDING,
            plus_ones=1,
        )

    def _eligible_person(self, name):
        person = Person.objects.create(
            name=name,
            email=f"{name.lower()}@example.com",
        )
        person.games.add(self.game)
        person.availability.add(*self.required_day_hours)
        return person

    def test_builds_email_with_event_details_attendance_and_links(self):
        email = build_event_invitation_email(self.event, self.recipient)

        self.assertIn("Catan", email.body)
        self.assertIn("Saturday, October 17, 2026", email.body)
        self.assertIn("4:00 PM", email.body)
        self.assertIn("The Parlour, Sidney, MT", email.body)
        self.assertIn("https://www.facebook.com/theparlour.mt/", email.body)
        self.assertIn(self.game.boardgamegeek_url, email.body)
        self.assertIn("3 people are currently going", email.body)
        self.assertIn("looking for 3 more", email.body)
        self.assertIn("welcome to bring a plus one", email.body)
        self.assertIn("Please reply to this email", email.body)
        self.assertIn("only reserved after you respond", email.body)

    def test_plus_one_language_is_omitted_when_fewer_than_two_spots_remain(self):
        self.game.max_players = 4
        self.game.save(update_fields=["max_players"])

        email = build_event_invitation_email(self.event, self.recipient)

        self.assertEqual(email.remaining_spots, 1)
        self.assertNotIn("welcome to bring a plus one", email.body)

    def test_leader_and_attending_invitation_plus_ones_are_counted_once(self):
        Invitation.objects.create(
            event=self.event,
            person=self.leader,
            invited_at=aware(2026, 10, 1),
            result=Invitation.Result.ATTENDING,
            plus_ones=2,
        )

        self.assertEqual(get_current_attendance(self.event), 5)

    def test_owner_who_is_also_leader_counts_as_one_automatic_attendee(self):
        Invitation.objects.filter(event=self.event).delete()

        self.assertEqual(get_current_attendance(self.event), 1)

    def test_distinct_owner_and_leader_each_count_as_automatic_attendees(self):
        Invitation.objects.filter(event=self.event).delete()
        other_leader = Person.objects.create(
            name="Other Leader", email="other-leader@example.com"
        )
        self.event.leader = other_leader
        self.event.save(update_fields=["leader"])

        self.assertEqual(get_current_attendance(self.event), 2)

    def test_owner_and_leader_legacy_attending_invitations_do_not_double_count(self):
        Invitation.objects.filter(event=self.event).delete()
        other_leader = Person.objects.create(
            name="Other Leader", email="other-leader@example.com"
        )
        self.event.leader = other_leader
        self.event.save(update_fields=["leader"])
        Invitation.objects.create(
            event=self.event,
            person=self.leader,
            invited_at=aware(2026, 10, 1),
            result=Invitation.Result.ATTENDING,
            plus_ones=1,
        )
        Invitation.objects.create(
            event=self.event,
            person=other_leader,
            invited_at=aware(2026, 10, 1),
            result=Invitation.Result.ATTENDING,
            plus_ones=2,
        )

        self.assertEqual(get_current_attendance(self.event), 5)

    @patch("planner.services.event_invitations.send_email")
    def test_sending_eligible_person_creates_pending_invitation_once(self, mocked_send):
        mocked_send.return_value = "gmail-message-id"

        result = send_event_invitation(self.event, self.recipient)

        self.assertEqual(result.message_id, "gmail-message-id")
        invitation = Invitation.objects.get(event=self.event, person=self.recipient)
        self.assertEqual(invitation.result, Invitation.Result.PENDING)
        self.assertNotEqual(invitation.result, Invitation.Result.ATTENDING)
        mocked_send.assert_called_once_with(
            self.recipient.email,
            result.email.subject,
            result.email.body,
        )

        with self.assertRaises(EventInvitationAlreadyExistsError):
            send_event_invitation(self.event, self.recipient)
        mocked_send.assert_called_once()

    @patch("planner.services.event_invitations.send_email")
    def test_ineligible_person_is_rejected_without_sending(self, mocked_send):
        ineligible_person = Person.objects.create(
            name="Ineligible", email="ineligible@example.com"
        )

        with self.assertRaises(EventInvitationIneligibleError):
            send_event_invitation(self.event, ineligible_person)

        mocked_send.assert_not_called()
        self.assertFalse(Invitation.objects.filter(person=ineligible_person).exists())
