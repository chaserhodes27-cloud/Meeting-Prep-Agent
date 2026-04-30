import json
import os
import secrets
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from io import BytesIO

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_mail import Mail, Message
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

load_dotenv()

# Allow OAuth over HTTP for local dev
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/oauth2callback")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key-change-in-production")

database_url = os.getenv("DATABASE_URL", "sqlite:///meeting_prep.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = ("MeetPrep", os.getenv("MAIL_USERNAME", ""))

from models import Briefing, User, db  # noqa: E402

db.init_app(app)
mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)


# --- Forms ---

class SignUpForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=80)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create Account")

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError("Username already taken.")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError("An account with that email already exists.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")


class ProfileForm(FlaskForm):
    profile_bio = StringField("Your background & goals")
    submit = SubmitField("Save")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send Reset Link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")])
    submit = SubmitField("Reset Password")


# --- In-memory job store ---

jobs = {}


def push(job_id: str, msg: str):
    jobs[job_id]["messages"].append(msg)


def send_briefing_email(to_email: str, meeting_title: str, briefing_md: str):
    if not SENDGRID_API_KEY or not FROM_EMAIL:
        return
    try:
        import markdown as md
        import sendgrid
        from sendgrid.helpers.mail import Content, Email, Mail, To

        html_body = md.markdown(briefing_md, extensions=["extra"])
        html = f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:680px;margin:0 auto;padding:2rem;color:#1a1a1a;">
          <div style="margin-bottom:1.5rem;">
            <span style="display:inline-block;background:linear-gradient(135deg,#7c3aed,#2563eb);color:white;padding:0.3rem 0.75rem;border-radius:6px;font-size:0.8rem;font-weight:600;">MeetPrep</span>
          </div>
          <h2 style="margin-bottom:1.5rem;font-size:1.3rem;">Briefing: {meeting_title}</h2>
          {html_body}
          <hr style="margin-top:2rem;border:none;border-top:1px solid #eee;">
          <p style="font-size:0.75rem;color:#999;margin-top:1rem;">Generated by MeetPrep</p>
        </div>"""

        message = Mail(
            from_email=Email(FROM_EMAIL, "MeetPrep"),
            to_emails=To(to_email),
            subject=f"Briefing: {meeting_title}",
            html_content=Content("text/html", html),
        )
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        print(f"Email send failed: {e}")


def _get_google_flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )


def _get_google_credentials(user):
    if not user.google_credentials:
        return None
    from google.oauth2.credentials import Credentials
    data = json.loads(user.google_credentials)
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id", GOOGLE_CLIENT_ID),
        client_secret=data.get("client_secret", GOOGLE_CLIENT_SECRET),
        scopes=data.get("scopes", GOOGLE_SCOPES),
    )


def run_agent(
    job_id: str,
    input_type: str,
    text: str = None,
    ics_path: str = None,
    user_context: str = "",
    user_email: str = "",
    user_id: str = None,
    meeting_type: str = "general",
):
    with app.app_context():
        try:
            import anthropic
            from tavily import TavilyClient

            from main import (
                enrich_attendees,
                generate_briefing,
                make_output_path,
                parse_calendar_event,
                parse_ics,
                parse_text,
                research_attendee_linkedin,
                research_company_news,
            )

            anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

            push(job_id, "Parsing meeting invite...")

            if input_type == "text":
                meeting = parse_text(text, anthropic_client)
            elif input_type == "calendar":
                meeting = parse_calendar_event(json.loads(text))
            else:
                meeting = parse_ics(ics_path)

            n = len(meeting.get("attendees", []))
            push(job_id, f"Found {n} attendee{'s' if n != 1 else ''} — {meeting['title']}")

            attendees = [a for a in meeting["attendees"] if a["email"] != user_email.lower()]
            attendees = enrich_attendees(attendees)
            meeting["attendees"] = attendees

            research = {"linkedin": {}, "news": {}}
            seen_domains = set()

            for att in attendees:
                name = att["name"] or att["email"]
                domain = att["company_domain"]
                email = att["email"]

                push(job_id, f"Searching LinkedIn for {name}...")
                research["linkedin"][email] = research_attendee_linkedin(name, domain, tavily_client)

                if domain and domain not in seen_domains:
                    push(job_id, f"Fetching company news for {domain}...")
                    research["news"][domain] = research_company_news(domain, tavily_client)
                    seen_domains.add(domain)

            push(job_id, "Generating briefing with Claude...")
            briefing_md = generate_briefing(meeting, research, anthropic_client, user_context, meeting_type)

            output_path = make_output_path(meeting)
            with open(output_path, "w") as f:
                f.write(briefing_md)

            dt_obj = meeting.get("_dt_obj")
            meeting_dt = None
            if dt_obj and hasattr(dt_obj, "strftime"):
                try:
                    if hasattr(dt_obj, "hour"):
                        meeting_dt = dt_obj.replace(tzinfo=None)
                    else:
                        meeting_dt = datetime.combine(dt_obj, datetime.min.time())
                except Exception:
                    pass

            record = Briefing(
                user_id=user_id,
                title=meeting.get("title", "Untitled Meeting"),
                meeting_type=meeting_type,
                meeting_datetime=meeting_dt,
                content=briefing_md,
            )
            db.session.add(record)
            db.session.commit()

            jobs[job_id]["result"] = briefing_md
            jobs[job_id]["briefing_id"] = record.id
            jobs[job_id]["status"] = "done"
            push(job_id, f"Saved to {output_path}")

            send_briefing_email(user_email, meeting.get("title", "Your Meeting"), briefing_md)
            if SENDGRID_API_KEY and FROM_EMAIL:
                push(job_id, f"Briefing emailed to {user_email}")

        except BaseException as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e) or "An unexpected error occurred."
        finally:
            if ics_path and os.path.exists(ics_path):
                os.unlink(ics_path)


# --- Google Calendar OAuth ---

@app.route("/connect-google")
@login_required
def connect_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash("Google credentials are not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to your .env file and restart the server.", "error")
        return redirect(url_for("profile"))
    flow = _get_google_flow()
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    session["google_oauth_state"] = state
    session["google_code_verifier"] = getattr(flow, "code_verifier", None)
    return redirect(auth_url)


@app.route("/oauth2callback")
@login_required
def oauth2callback():
    flow = _get_google_flow()
    code_verifier = session.pop("google_code_verifier", None)
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    current_user.google_credentials = json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or GOOGLE_SCOPES),
    })
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/disconnect-google")
@login_required
def disconnect_google():
    current_user.google_credentials = None
    db.session.commit()
    return redirect(url_for("profile"))


@app.route("/api/upcoming-meetings")
@login_required
def upcoming_meetings():
    creds = _get_google_credentials(current_user)
    if not creds:
        return jsonify({"error": "Not connected"}), 401

    try:
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            current_user.google_credentials = json.dumps({
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or GOOGLE_SCOPES),
            })
            db.session.commit()

        service = build("calendar", "v3", credentials=creds)
        now = datetime.utcnow().isoformat() + "Z"
        week_later = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=week_later,
            maxResults=15,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for ev in result.get("items", []):
            attendees = ev.get("attendees", [])
            if len(attendees) < 2:
                continue
            start = ev.get("start", {})
            events.append({
                "id": ev.get("id"),
                "title": ev.get("summary", "Untitled"),
                "datetime": start.get("dateTime") or start.get("date"),
                "attendees": [
                    {"name": a.get("displayName", ""), "email": a.get("email", "")}
                    for a in attendees
                ],
            })

        return jsonify(events)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Auth routes ---

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = SignUpForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data.lower())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("index"))
    return render_template("signup.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
        form.email.errors.append("Invalid email or password.")
    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = ForgotPasswordForm()
    sent = False
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                msg = Message(
                    subject="Reset your MeetPrep password",
                    recipients=[user.email],
                    html=f"""
                    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:520px;margin:0 auto;padding:2rem;color:#1a1a1a;">
                      <div style="margin-bottom:1.5rem;">
                        <span style="display:inline-block;background:linear-gradient(135deg,#7c3aed,#2563eb);color:white;padding:0.3rem 0.75rem;border-radius:6px;font-size:0.8rem;font-weight:600;">MeetPrep</span>
                      </div>
                      <h2 style="font-size:1.2rem;margin-bottom:0.75rem;">Reset your password</h2>
                      <p style="color:#555;margin-bottom:1.5rem;">Click the button below to set a new password. This link expires in 1 hour.</p>
                      <a href="{reset_url}" style="display:inline-block;padding:0.7rem 1.5rem;background:linear-gradient(135deg,#7c3aed,#2563eb);color:white;text-decoration:none;border-radius:8px;font-weight:600;font-size:0.9rem;">Reset Password</a>
                      <p style="margin-top:1.5rem;font-size:0.75rem;color:#999;">If you didn't request this, ignore this email. Your password won't change.</p>
                    </div>""",
                )
                mail.send(msg)
            except Exception as e:
                print(f"Password reset email failed: {e}")
        # Always show success to avoid revealing which emails are registered
        sent = True
    return render_template("forgot_password.html", form=form, sent=sent)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        return render_template("reset_password.html", form=None, invalid=True)
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        login_user(user)
        return redirect(url_for("index"))
    return render_template("reset_password.html", form=form, invalid=False)


# --- App routes ---

@app.route("/")
@login_required
def index():
    return render_template(
        "index.html",
        user=current_user,
        profile_bio=current_user.profile_bio or "",
        google_connected=bool(current_user.google_credentials),
        google_configured=bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.profile_bio = form.profile_bio.data.strip()
        db.session.commit()
        return redirect(url_for("index"))
    return render_template(
        "profile.html",
        user=current_user,
        form=form,
        google_connected=bool(current_user.google_credentials),
        google_configured=bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    )


@app.route("/history")
@login_required
def history():
    briefings = (
        Briefing.query.filter_by(user_id=current_user.id)
        .order_by(Briefing.created_at.desc())
        .all()
    )
    return render_template("history.html", user=current_user, briefings=briefings)


@app.route("/api/briefings")
@login_required
def api_briefings():
    briefings = (
        Briefing.query.filter_by(user_id=current_user.id)
        .order_by(Briefing.created_at.desc())
        .all()
    )
    return jsonify([
        {
            "id": b.id,
            "title": b.title,
            "meeting_datetime": b.meeting_datetime.isoformat() if b.meeting_datetime else None,
            "created_at": b.created_at.isoformat(),
        }
        for b in briefings
    ])


@app.route("/briefing/<briefing_id>")
@login_required
def get_briefing(briefing_id):
    record = Briefing.query.filter_by(id=briefing_id, user_id=current_user.id).first()
    if not record:
        return jsonify({"error": "Not found."}), 404
    return jsonify({"title": record.title, "content": record.content})


@app.route("/generate", methods=["POST"])
@login_required
def generate():
    if not ANTHROPIC_API_KEY or not TAVILY_API_KEY:
        return jsonify({"error": "API keys not configured on the server."}), 500

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "running",
        "messages": [],
        "result": None,
        "briefing_id": None,
        "error": None,
        "user_id": current_user.id,
    }

    input_type = request.form.get("input_type", "text")
    user_context = request.form.get("user_context", "").strip()
    meeting_type = request.form.get("meeting_type", "general")
    user_email = current_user.email
    user_id = current_user.id

    if input_type == "calendar":
        calendar_data = request.form.get("calendar_data", "").strip()
        if not calendar_data:
            return jsonify({"error": "No calendar event data provided."}), 400
        t = threading.Thread(
            target=run_agent,
            kwargs={
                "job_id": job_id,
                "input_type": "calendar",
                "text": calendar_data,
                "user_context": user_context,
                "user_email": user_email,
                "user_id": user_id,
                "meeting_type": meeting_type,
            },
        )
    elif input_type == "text":
        text = request.form.get("meeting_text", "").strip()
        if not text:
            return jsonify({"error": "No meeting text provided."}), 400
        t = threading.Thread(
            target=run_agent,
            kwargs={
                "job_id": job_id,
                "input_type": "text",
                "text": text,
                "user_context": user_context,
                "user_email": user_email,
                "user_id": user_id,
                "meeting_type": meeting_type,
            },
        )
    else:
        file = request.files.get("ics_file")
        if not file or not file.filename:
            return jsonify({"error": "No .ics file provided."}), 400
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ics")
        file.save(tmp.name)
        tmp.close()
        t = threading.Thread(
            target=run_agent,
            kwargs={
                "job_id": job_id,
                "input_type": "ics",
                "ics_path": tmp.name,
                "user_context": user_context,
                "user_email": user_email,
                "user_id": user_id,
                "meeting_type": meeting_type,
            },
        )

    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
@login_required
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    if job.get("user_id") != current_user.id:
        return jsonify({"error": "Forbidden."}), 403
    return jsonify({
        "status": job["status"],
        "messages": job["messages"],
        "result": job["result"],
        "briefing_id": job.get("briefing_id"),
        "error": job["error"],
    })


@app.route("/download/<briefing_id>")
@login_required
def download(briefing_id):
    record = Briefing.query.filter_by(id=briefing_id, user_id=current_user.id).first()
    if not record:
        return "Not found.", 404
    slug = record.title.lower().replace(" ", "-")[:40]
    filename = f"{slug}.md"
    data = record.content.encode("utf-8")
    return send_file(BytesIO(data), as_attachment=True, download_name=filename, mimetype="text/markdown")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001)
