from ._survey_request_email import SurveyRequestEmailCommand


class Command(SurveyRequestEmailCommand):
    help = "Send an initial request for the general survey."
    request_type = "initial"
