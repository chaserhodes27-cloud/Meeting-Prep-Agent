# Meeting Prep Workflow

## What This Does

Takes a meeting invite and automatically:
1. Extracts attendees, time, and title
2. Looks up each attendee's LinkedIn profile (via public search)
3. Pulls recent news about their companies
4. Asks Claude to write a structured briefing doc

The briefing is saved as a Markdown file in `output/`.

---

## Setup (One Time)

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create your `.env` file** (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```
   Then fill in your API keys:
   - `TAVILY_API_KEY` — get one free at https://tavily.com
   - `ANTHROPIC_API_KEY` — get one at https://console.anthropic.com
   - `MY_EMAIL` — your email address (so the agent skips researching you)

---

## Running the Agent

**Option A — From a .ics calendar file:**
```bash
python main.py --input path/to/meeting.ics
```

To export a .ics from Google Calendar: open an event → three dots → "Copy to" or use the Google Takeout export. From Outlook: open event → File → Save As → iCalendar.

**Option B — From pasted invite text:**
```bash
python main.py --text "Meeting with Jane Smith (jane@openai.com) and Bob Lee (bob@microsoft.com) on Tuesday April 22 at 2pm. Topic: Partnership discussion."
```

---

## Output

Briefings are saved to `output/YYYY-MM-DD_meeting-title.md`.

Example structure:
```
# Meeting Briefing: Partnership Discussion

## Meeting Overview
- Title: Partnership Discussion
- Date/Time: Tuesday, April 22, 2025 at 2:00 PM
- Attendees:
  - Jane Smith (jane@openai.com)
  - Bob Lee (bob@microsoft.com)

## Attendees

### Jane Smith
- Role/Company: Senior Partnerships Lead at OpenAI
- Background: ...
- LinkedIn Highlights: ...

### Bob Lee
- Role/Company: ...

## Company News

### openai.com
- ...

### microsoft.com
- ...

## Suggested Talking Points
- ...
```

---

## Notes

- If an attendee has no public LinkedIn profile, the agent will note "Not found" rather than guessing.
- Company news is searched per unique domain, so two attendees from the same company only trigger one search.
- The agent filters out your own email (`MY_EMAIL`) so it doesn't research you.
