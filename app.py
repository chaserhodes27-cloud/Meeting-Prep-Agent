import os
import tempfile
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

app = Flask(__name__)

# In-memory job store: job_id -> {status, messages, result, output_path, error}
jobs = {}


def push(job_id: str, msg: str):
    jobs[job_id]["messages"].append(msg)


def run_agent(job_id: str, input_type: str, text: str = None, ics_path: str = None):
    try:
        import anthropic
        from tavily import TavilyClient

        from main import (
            enrich_attendees,
            filter_self,
            generate_briefing,
            make_output_path,
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
        else:
            meeting = parse_ics(ics_path)

        n = len(meeting.get("attendees", []))
        push(job_id, f"Found {n} attendee{'s' if n != 1 else ''} — {meeting['title']}")

        attendees = filter_self(meeting["attendees"])
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
        briefing = generate_briefing(meeting, research, anthropic_client)

        output_path = make_output_path(meeting)
        with open(output_path, "w") as f:
            f.write(briefing)

        jobs[job_id]["result"] = briefing
        jobs[job_id]["output_path"] = output_path
        jobs[job_id]["status"] = "done"
        push(job_id, f"Saved to {output_path}")

    except BaseException as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e) or "An unexpected error occurred."
    finally:
        if ics_path and os.path.exists(ics_path):
            os.unlink(ics_path)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    if not ANTHROPIC_API_KEY or not TAVILY_API_KEY:
        return jsonify({"error": "API keys not configured in .env"}), 500

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "messages": [], "result": None, "output_path": None, "error": None}

    input_type = request.form.get("input_type", "text")

    if input_type == "text":
        text = request.form.get("meeting_text", "").strip()
        if not text:
            return jsonify({"error": "No meeting text provided."}), 400
        t = threading.Thread(target=run_agent, kwargs={"job_id": job_id, "input_type": "text", "text": text})

    else:
        file = request.files.get("ics_file")
        if not file or not file.filename:
            return jsonify({"error": "No .ics file provided."}), 400
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ics")
        file.save(tmp.name)
        tmp.close()
        t = threading.Thread(target=run_agent, kwargs={"job_id": job_id, "input_type": "ics", "ics_path": tmp.name})

    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify({
        "status": job["status"],
        "messages": job["messages"],
        "result": job["result"],
        "error": job["error"],
    })


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or not job.get("output_path"):
        return "Not found.", 404
    path = Path(job["output_path"]).resolve()
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="text/markdown")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
