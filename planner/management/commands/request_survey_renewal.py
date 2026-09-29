from ._survey_request_email import SurveyRequestEmailCommand


class Command(SurveyRequestEmailCommand):
    help = "Send a general-survey renewal request."
    request_type = "renewal"
