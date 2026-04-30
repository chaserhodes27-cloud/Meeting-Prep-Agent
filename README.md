# Meeting Prep Agent

**Never walk into a meeting unprepared again.**

Meeting Prep Agent researches your attendees, pulls the latest company news, and delivers a personalized briefing doc — in under a minute.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-meeting--prep--agent-7c3aed?style=for-the-badge&logo=render&logoColor=white)](https://meeting-prep-agent-tyuy.onrender.com)

---

## Features

- **AI-powered attendee research** — Claude searches LinkedIn profiles and company news for every person in the meeting
- **Personalized talking points** — set your background and goals once; every briefing is written specifically for you
- **Google Calendar integration** — connect your calendar and prep any upcoming meeting in one click
- **Multi-user authentication** — secure signup, login, and fully isolated per-user data
- **Briefing history** — every briefing is saved to your account so you can reference it later
- **Downloadable docs** — export any briefing as a `.md` file
- **Dark-themed responsive UI** — clean, fast, works on any screen size

---

## Demo

Paste a meeting invite (or upload a `.ics` file), click **Generate Briefing**, and watch the agent work in real time. A live status log tracks each step — researching attendees, fetching company news, generating with Claude — then the finished briefing renders as formatted markdown. Connect Google Calendar to pull upcoming meetings directly into the app.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask |
| AI | Anthropic Claude API (`claude-sonnet-4-6`) |
| Research | Tavily Search API |
| Auth | Flask-Login, Flask-WTF |
| Database | SQLAlchemy, PostgreSQL (SQLite for local dev) |
| Calendar | Google Calendar API (OAuth 2.0) |
| Hosting | Render |

---

## Running Locally

**1. Clone the repo**
```bash
git clone https://github.com/chaserhodes27-cloud/Meeting-Prep-Agent.git
cd Meeting-Prep-Agent
```

**2. Install dependencies**
```bash
pip3 install -r requirements.txt
```

**3. Configure environment variables**
```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
ANTHROPIC_API_KEY=your-key         # anthropic.com
TAVILY_API_KEY=your-key            # tavily.com
SECRET_KEY=any-random-string

# Optional: Google Calendar
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-secret
GOOGLE_REDIRECT_URI=https://meeting-prep-agent-tyuy.onrender.com/oauth2callback
```

**4. Start the server**
```bash
python3 app.py
```

Open [https://meeting-prep-agent-tyuy.onrender.com](https://meeting-prep-agent-tyuy.onrender.com), create an account, and generate your first briefing.

---

## Screenshots

> _Coming soon_

---

## Built by

**Chase Rhodes** — [github.com/chaserhodes27-cloud](https://github.com/chaserhodes27-cloud)
