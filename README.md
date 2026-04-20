# Meeting Prep Agent 🤝

An AI agent that automatically researches your meeting attendees and generates a structured briefing doc before you walk into any meeting.

## What it does
- Parses meeting invites (.ics files or pasted text)
- Researches each attendee's background and LinkedIn profile
- Fetches recent news about their company
- Generates a structured briefing with talking points

## Demo
![Meeting Prep Agent Output](output/sample.png)

## Tech Stack
- Python
- Anthropic Claude API (claude-sonnet-4-5)
- Tavily Search API
- icalendar

## Setup
1. Clone the repo
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your API keys
4. Run it!

## Usage
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
