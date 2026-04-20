# Meeting Prep Agent 🤝

An AI agent that automatically researches your meeting attendees and generates a structured briefing doc before you walk into any meeting. Available as both a **web UI** and a **CLI**.

## What it does
- Parses meeting invites (.ics files or pasted text)
- Researches each attendee's background and LinkedIn profile
- Fetches recent news about their company
- Generates a structured briefing with talking points

## Demo

The web UI is a dark-themed single-page app where you paste meeting details (or upload a `.ics` file) and click **Generate Briefing**. A live status log shows each research step as it runs — searching LinkedIn, fetching company news, generating with Claude — then the finished briefing renders as formatted markdown on the same page. A download button saves the `.md` file locally.

## Tech Stack
- Python + Flask
- Anthropic Claude API (claude-sonnet-4-6)
- Tavily Search API
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
Then open [http://localhost:5001](http://localhost:5001) in your browser.

### CLI
```bash
# With a .ics calendar file
python3 main.py --input meeting.ics

# With pasted text
python3 main.py --text "Meeting with John at john@stripe.com on Friday at 3pm"
```

## Output
Briefings are saved to `output/YYYY-MM-DD_meeting-title.md`

## Built by
Chase Rhodes — [github.com/chaserhodes27-cloud](https://github.com/chaserhodes27-cloud)
