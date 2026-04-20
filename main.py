import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MY_EMAIL = os.getenv("MY_EMAIL", "").lower()

SYSTEM_PROMPT = """You are a professional meeting preparation assistant. Your job is to produce a structured briefing document in Markdown format based on research data provided to you.

Follow this exact output structure — do not add or remove sections:

# Meeting Briefing: {MEETING_TITLE}

## Meeting Overview
- **Title:** {title}
- **Date/Time:** {datetime}
- **Attendees:** bulleted list of name (email) for each attendee

## Attendees

For each attendee, write:

### {Attendee Full Name}
- **Role/Company:** (role and company from LinkedIn research, or "Unknown")
- **Background:** 2-3 sentence summary of who they are and what they do professionally
- **LinkedIn Highlights:** 2-3 bullet points of notable career history, recent activity, or expertise

(Repeat for each attendee)

## Company News

For each company represented by attendees, write:

### {Company Name}
- Bullet point for each notable recent headline or development, with approximate date if available

## Suggested Talking Points
- 3-5 actionable bullet points tailored to the attendees' backgrounds and the company context

Rules you must follow:
- Be concise. Use bullet points, not paragraphs, except where noted.
- If any information is missing or not found, write "Not found" — never fabricate or guess details.
- Only use information provided in the research data. Do not add information from your own knowledge.
- Replace {MEETING_TITLE}, {title}, {datetime} with the actual values from the meeting data.
"""


def parse_ics(filepath: str) -> dict:
    from icalendar import Calendar

    with open(filepath, "rb") as f:
        cal = Calendar.from_ical(f.read())

    meeting = {"title": None, "datetime": None, "attendees": []}

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        meeting["title"] = str(component.get("SUMMARY", "Untitled Meeting"))

        dtstart = component.get("DTSTART")
        if dtstart:
            dt = dtstart.dt
            if hasattr(dt, "strftime"):
                if hasattr(dt, "hour"):
                    meeting["datetime"] = dt.strftime("%A, %B %d, %Y at %I:%M %p %Z").strip()
                    meeting["_dt_obj"] = dt
                else:
                    meeting["datetime"] = dt.strftime("%A, %B %d, %Y")
                    meeting["_dt_obj"] = datetime.combine(dt, datetime.min.time())

        organizer = component.get("ORGANIZER")
        if organizer:
            email = str(organizer).replace("mailto:", "").lower()
            cn = organizer.params.get("CN", "") if hasattr(organizer, "params") else ""
            meeting["attendees"].append({"name": str(cn), "email": email})

        attendees = component.get("ATTENDEE")
        if attendees:
            if not isinstance(attendees, list):
                attendees = [attendees]
            for att in attendees:
                email = str(att).replace("mailto:", "").lower()
                cn = att.params.get("CN", "") if hasattr(att, "params") else ""
                meeting["attendees"].append({"name": str(cn), "email": email})

    meeting["attendees"] = _dedupe_attendees(meeting["attendees"])
    return meeting


def parse_text(raw_text: str, client) -> dict:
    prompt = f"""Extract meeting details from the text below and return valid JSON only — no explanation, no markdown fences.

JSON format:
{{"title": "...", "datetime": "...", "attendees": [{{"name": "...", "email": "..."}}]}}

Use null for any field not found. Extract all attendees including organizers.

Meeting text:
{raw_text}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Error: Could not parse meeting details from text. Please check your input.", file=sys.stderr)
        sys.exit(1)

    meeting = {
        "title": data.get("title") or "Untitled Meeting",
        "datetime": data.get("datetime") or "Unknown",
        "attendees": [],
        "_dt_obj": None,
    }

    for att in data.get("attendees") or []:
        name = att.get("name") or ""
        email = (att.get("email") or "").lower()
        if email:
            meeting["attendees"].append({"name": name, "email": email})

    meeting["attendees"] = _dedupe_attendees(meeting["attendees"])
    return meeting


def _dedupe_attendees(attendees: list) -> list:
    seen = set()
    result = []
    for att in attendees:
        key = att["email"]
        if key and key not in seen:
            seen.add(key)
            result.append(att)
    return result


def filter_self(attendees: list) -> list:
    if not MY_EMAIL:
        return attendees
    return [a for a in attendees if a["email"] != MY_EMAIL]


def enrich_attendees(attendees: list) -> list:
    for att in attendees:
        email = att["email"]
        domain = email.split("@")[-1] if "@" in email else ""
        att["company_domain"] = domain
    return attendees


def research_attendee_linkedin(name: str, domain: str, tavily_client) -> str:
    query = f"{name} {domain} LinkedIn"
    try:
        results = tavily_client.search(
            query=query,
            search_depth="advanced",
            include_domains=["linkedin.com"],
            max_results=3,
        )
        snippets = [r.get("content", "") for r in results.get("results", []) if r.get("content")]
        if not snippets:
            return "No public LinkedIn profile found."
        return "\n".join(snippets[:3])
    except Exception as e:
        print(f"  Warning: LinkedIn search failed for {name}: {e}", file=sys.stderr)
        return "No public LinkedIn profile found."


def research_company_news(domain: str, tavily_client) -> str:
    company_name = domain.split(".")[0].capitalize()
    query = f"{company_name} {domain} news 2025 2026"
    try:
        results = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=5,
        )
        snippets = []
        for r in results.get("results", []):
            title = r.get("title", "")
            snippet = r.get("content", "")[:200]
            if title:
                snippets.append(f"- {title}: {snippet}")
        if not snippets:
            return "No recent news found."
        return "\n".join(snippets)
    except Exception as e:
        print(f"  Warning: News search failed for {domain}: {e}", file=sys.stderr)
        return "No recent news found."


def build_user_prompt(meeting: dict, research: dict) -> str:
    attendee_lines = "\n".join(
        f"- {a['name']} ({a['email']})" if a["name"] else f"- {a['email']}"
        for a in meeting["attendees"]
    )

    research_blocks = []
    for att in meeting["attendees"]:
        email = att["email"]
        name = att["name"] or email
        domain = att.get("company_domain", "")
        linkedin = research["linkedin"].get(email, "No public LinkedIn profile found.")
        news = research["news"].get(domain, "No recent news found.")
        research_blocks.append(
            f"--- {name} ({email}) ---\n"
            f"LinkedIn Research:\n{linkedin}\n\n"
            f"Company News ({domain}):\n{news}"
        )

    research_text = "\n\n".join(research_blocks)

    return f"""Here is the meeting and research data. Generate the briefing now.

MEETING:
Title: {meeting['title']}
Date/Time: {meeting['datetime']}
Attendees:
{attendee_lines}

RESEARCH:
{research_text}"""


def generate_briefing(meeting: dict, research: dict, client) -> str:
    user_prompt = build_user_prompt(meeting, research)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    return response.content[0].text


def make_output_path(meeting: dict) -> str:
    dt_obj = meeting.get("_dt_obj")
    if dt_obj and hasattr(dt_obj, "strftime"):
        try:
            date_str = dt_obj.strftime("%Y-%m-%d")
        except Exception:
            date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    title = meeting.get("title", "meeting")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:60]

    os.makedirs("output", exist_ok=True)
    return f"output/{date_str}_{slug}.md"


def main():
    if not TAVILY_API_KEY:
        print("Error: TAVILY_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Meeting Prep Agent — generates a research briefing from a meeting invite."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", metavar="FILE", help="Path to a .ics calendar file")
    group.add_argument("--text", metavar="TEXT", help="Pasted meeting invite text")
    args = parser.parse_args()

    import anthropic
    from tavily import TavilyClient

    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

    print("Parsing meeting invite...")
    if args.input:
        meeting = parse_ics(args.input)
    else:
        meeting = parse_text(args.text, anthropic_client)

    if not meeting["attendees"]:
        print("Warning: No attendees found in the invite.", file=sys.stderr)

    print(f"  Title: {meeting['title']}")
    print(f"  Time:  {meeting['datetime']}")
    print(f"  Attendees: {len(meeting['attendees'])} found")

    attendees = filter_self(meeting["attendees"])
    attendees = enrich_attendees(attendees)
    meeting["attendees"] = attendees

    if not attendees:
        print("No attendees to research (only you were listed). Generating minimal briefing.")

    research = {"linkedin": {}, "news": {}}
    seen_domains = set()

    print("\nResearching attendees...")
    for att in attendees:
        name = att["name"] or att["email"]
        domain = att["company_domain"]
        email = att["email"]

        print(f"  Searching LinkedIn: {name}...")
        research["linkedin"][email] = research_attendee_linkedin(name, domain, tavily_client)

        if domain and domain not in seen_domains:
            print(f"  Fetching company news: {domain}...")
            research["news"][domain] = research_company_news(domain, tavily_client)
            seen_domains.add(domain)

    print("\nGenerating briefing with Claude...")
    briefing = generate_briefing(meeting, research, anthropic_client)

    output_path = make_output_path(meeting)
    with open(output_path, "w") as f:
        f.write(briefing)

    print(f"\nBriefing saved to: {output_path}")


if __name__ == "__main__":
    main()
