# Kessler Gaming Event Planner

Kessler Gaming Event Planner organizes Kessler Gaming's invitation-only tabletop events at The Parlour in Sidney, Montana. Django runs locally, while PostgreSQL is hosted on Render. There is no public deployment.

## Local setup (Windows PowerShell)

The project currently uses **Python 3.11.4**. From a fresh checkout:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create `.env` in the repository root. Use the Render PostgreSQL **External Database URL** for `DATABASE_URL`; it must use SSL. Do not commit this file.

```dotenv
# Replace the secret key and database URL before starting the app.
DEBUG=true
DJANGO_SECRET_KEY=replace-with-a-long-random-local-secret
DATABASE_URL=postgresql://DATABASE_USER:DATABASE_PASSWORD@DATABASE_HOST:DATABASE_PORT/DATABASE_NAME?sslmode=require

# Optional override used by Survey Updates.
# GENERAL_SURVEY_FORM_ID=your-google-form-id

# Optional overrides for the default credential and token paths.
# GOOGLE_CREDENTIALS_PATH=C:\path\to\credentials.json
# GOOGLE_TOKEN_PATH=C:\path\to\token.json
```

`DJANGO_SECRET_KEY`, `DATABASE_URL`, and `DEBUG` are the relevant local settings. With `DEBUG=true`, the default allowed hosts include `localhost` and `127.0.0.1`; no `ALLOWED_HOSTS` or `CSRF_TRUSTED_ORIGINS` setting is needed for normal local use.

## Run the app locally

For an existing configured Render database, activate the environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py check
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. Log in with a staff/superuser account to access **Events**, **Availability**, **Form Submissions**, and **Survey Updates**.

## First-time database initialization

Run these commands only for a new, empty database:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py check
python manage.py runserver
```

After Django is running, sign in at <http://127.0.0.1:8000/admin/> and add the `Day` and `Hour` records. Then generate availability reference data in this required order (from another activated PowerShell window if the server is still running):

```powershell
python manage.py create_day_hours
python manage.py create_time_spans
```

`create_time_spans` requires the `DayHour` records created by `create_day_hours`. For later code/schema updates, an existing database can also require `python manage.py migrate`; do not run it merely as a connectivity or documentation check.

### Form configuration for a new database

No setup or sync command creates the matching `Form` record. Before using **Form Submissions**, **Survey Updates**, or survey-request email commands, add it in Django admin under **Forms**. Enter a `name` and the built-in general-survey Google Form ID as `google_form_id`; `survey_url` is optional in the model but must contain the public respondent URL before survey-request emails can be sent. The form ID is unique.

## Google Forms and Gmail

Create a Google Cloud **Desktop OAuth client** and save the downloaded client JSON as `credentials.json` in the repository root. The shared authorized-user token is written to `token.json` there. Both paths can be overridden with `GOOGLE_CREDENTIALS_PATH` and `GOOGLE_TOKEN_PATH`, and both files are ignored by Git.

Enable these Google Cloud APIs:

- Google Forms API
- Gmail API

The shared authorization requests exactly these scopes:

- `https://www.googleapis.com/auth/forms.body.readonly`
- `https://www.googleapis.com/auth/forms.responses.readonly`
- `https://www.googleapis.com/auth/gmail.send`

Authorize on the local machine the first time, or again after revoking access or changing scopes:

```powershell
python manage.py authorize_google_integrations
```

This opens the installed-app browser flow and saves one token for both Forms and Gmail. Normal services and web requests do not launch the browser.

### General survey form resolution

When `GENERAL_SURVEY_FORM_ID` is omitted, Django settings fall back to the built-in general-survey form ID. **Survey Updates** uses this setting and requires a matching `Form` record in the database.

The **Form Submissions** sync button and `sync_google_form_responses` CLI command both call the same synchronization service. It uses the built-in general-survey form ID directly, rather than reading `GENERAL_SURVEY_FORM_ID`. The three survey-request email commands also use that configured-in-code form ID and require its matching `Form` record.

## Daily workflow

- **Import survey responses:** on **Form Submissions**, use **Sync Google Form Responses**, or run:

  ```powershell
  python manage.py sync_google_form_responses
  ```

- **Review unmatched submissions:** on **Form Submissions**, use **Create** to create a Person or **Update** to select an existing Person and apply the saved submission.

- **Send survey requests:** use **Survey Updates**, or preview a command-line initial-survey email without sending or recording it:

  ```powershell
  python manage.py request_initial_survey --person-id PERSON_ID --dry-run
  ```

- **Send an event invitation:** on **Events**, open **Invitation List** and select **Invite**. The command-line equivalent is:

  ```powershell
  python manage.py send_event_invitation --event EVENT_ID --person PERSON_ID
  ```

  A successful Gmail send creates or updates the pending Invitation; the command does not mark the person as attending.
