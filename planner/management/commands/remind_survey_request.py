from ._survey_request_email import SurveyRequestEmailCommand


class Command(SurveyRequestEmailCommand):
    help = "Send a reminder for the general survey."
    request_type = "reminder"
