# Meeting Prep Agent 🤝

A multi-user AI SaaS app that researches your meeting attendees and generates a personalized briefing doc before you walk into any meeting. Available as both a **web UI** and a **CLI**.

## What it does
- Parses meeting invites (.ics files, pasted text, or Google Calendar)
- Researches each attendee's background and LinkedIn profile
- Fetches recent news about their company
- Generates a structured briefing with talking points tailored to your background and goals

## Features
- **User accounts** — sign up, log in, log out; each user's data is fully isolated
- **Briefing history** — every generated briefing is saved and accessible from your account
- **Personalization** — set your background & goals once; Claude injects them into every briefing
- **Google Calendar integration** — connect your calendar to pull upcoming meetings directly into the app
- **Web UI + CLI** — browser-based app for most users, command-line for power users

## Demo

The web UI is a dark-themed single-page app where you paste meeting details (or upload a `.ics` file) and click **Generate Briefing**. A live status log shows each research step as it runs — searching LinkedIn, fetching company news, generating with Claude — then the finished briefing renders as formatted markdown on the same page. A download button saves the `.md` file locally.

## Tech Stack
- Python + Flask
- Flask-Login + Flask-WTF (authentication & forms)
- SQLAlchemy + SQLite (user accounts & briefing history)
- Anthropic Claude API (claude-sonnet-4-6)
- Tavily Search API
- Google Calendar API (OAuth 2.0)
- icalendar

## Setup
1. Clone the repo
2. Install dependencies: `pip3 install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your API keys
4. Run it!

## Usage

### Web UI (recommended)
```bash
python3 app.py
```
Then open [http://localhost:5001](http://localhost:5001) in your browser. Create an account, set your background & goals in your profile, and start generating briefings.

### CLI
```bash
# With a .ics calendar file
python3 main.py --input meeting.ics

# With pasted text
python3 main.py --text "Meeting with John at john@stripe.com on Friday at 3pm"
```

## Output
Briefings are saved to `output/YYYY-MM-DD_meeting-title.md` and stored in your account history.

## Built by
Chase Rhodes — [github.com/chaserhodes27-cloud](https://github.com/chaserhodes27-cloud)
