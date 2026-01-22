# Boswell: AI Research Interviewer

An open-source AI interviewer that joins Zoom/Meet calls, conducts research-informed interviews autonomously, and outputs structured transcripts and insights.

## Overview

Boswell is designed for researchers and journalists who need to conduct substantive interviews at scale without losing the human touch. You provide a topic and research materials, Boswell generates interview questions and dispatches an AI bot to your meeting. Your guest joins, and the AI conducts a dynamic, research-informed interview.

**Key Features:**
- Research-informed question generation from documents and URLs
- Dynamic conversation that follows interesting threads
- Automatic transcript cleanup and insight extraction
- Support for Google Meet, Zoom, and Microsoft Teams

## Quick Start

### Prerequisites

- Python 3.11+
- API keys for: Claude, ElevenLabs, Deepgram, MeetingBaaS

### Local Installation

```bash
# Clone the repository
git clone https://github.com/yourname/boswell
cd boswell

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys

# Initialize configuration
boswell init
```

### Docker Installation

```bash
# Clone and set up
git clone https://github.com/yourname/boswell
cd boswell
cp .env.example .env
# Edit .env with your API keys

# Build and run
docker-compose build
docker-compose run --rm boswell init

# Run commands
docker-compose run --rm boswell create --topic "Your topic"
docker-compose run --rm boswell list
```

## CLI Commands

### `boswell init`

Initialize Boswell configuration with API keys. Creates `~/.boswell/config.json` with your credentials and preferences.

```bash
boswell init
```

Prompts for:
- Claude API key (required)
- ElevenLabs API key (required)
- Deepgram API key (required)
- MeetingBaaS API key (required)
- Meeting provider preference (google_meet or zoom)
- Default interview times

### `boswell create`

Create a new interview session with research materials.

```bash
boswell create --topic "AI safety research" --docs ./research/paper.pdf,./notes.md --urls https://example.com/bio
```

**Options:**
- `--topic, -t` (required): Interview topic
- `--docs, -d`: Comma-separated paths to research documents (PDF, TXT, MD)
- `--urls, -u`: Comma-separated URLs to scrape for research

**What happens:**
1. Ingests research documents and URLs
2. Generates tailored interview questions using Claude
3. Prompts for a meeting URL (Google Meet, Zoom, or Teams)
4. Dispatches an AI bot to the meeting
5. Returns the interview ID for tracking

### `boswell status`

Check the status of an interview.

```bash
boswell status int_7x8f2k
```

**Possible statuses:**
- `pending`: Interview created, no bot dispatched
- `waiting`: Bot in meeting, waiting for guest
- `in_progress`: Interview actively happening
- `processing`: Interview complete, generating outputs
- `complete`: All outputs ready
- `no_show`: Guest didn't join within timeout
- `error`: Something went wrong

### `boswell wait`

Wait for guest to join the interview meeting with real-time status updates.

```bash
boswell wait int_7x8f2k --timeout 15
```

**Options:**
- `--timeout, -t`: Maximum wait time in minutes (default: 10)

Polls the bot status every 30 seconds and updates the interview status when the guest joins or timeout expires.

### `boswell list`

List all past interviews.

```bash
boswell list
```

Displays interview ID, status, creation date, and topic for all interviews.

### `boswell export`

Export interview outputs (transcript.md and insights.md).

```bash
boswell export int_7x8f2k --output ./interviews/ --transcript ./raw_transcript.json
```

**Options:**
- `--output, -o`: Output directory (default: `outputs/YYYY-MM-DD-guest-name/`)
- `--transcript, -t`: Path to raw transcript JSON file

**Outputs:**
- `transcript.md`: Clean, readable interview transcript with YAML frontmatter
- `insights.md`: Key themes, notable quotes, and summary

### `boswell retry`

Retry a no-show or failed interview with a new meeting link.

```bash
boswell retry int_7x8f2k
```

Available for interviews with status: pending, no_show, or error.

## Configuration

### Config File (~/.boswell/config.json)

```json
{
  "claude_api_key": "sk-ant-...",
  "elevenlabs_api_key": "...",
  "deepgram_api_key": "...",
  "meetingbaas_api_key": "...",
  "meeting_provider": "google_meet",
  "default_target_time": 30,
  "default_max_time": 45
}
```

### Environment Variables

You can also configure Boswell using environment variables in a `.env` file:

```bash
CLAUDE_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
DEEPGRAM_API_KEY=...
MEETINGBAAS_API_KEY=...
```

## Example Workflow

```bash
# 1. Initialize configuration (one-time)
boswell init

# 2. Prepare research materials
# - PDFs, text files, or markdown documents about your guest/topic
# - URLs to their bio, publications, or relevant pages

# 3. Create the interview
boswell create \
  --topic "Future of AI governance" \
  --docs ./research/guest-publications.pdf,./prep-notes.md \
  --urls https://guest-bio.com

# 4. Share the meeting link with your guest
# The CLI will display the link to share

# 5. Wait for the guest (optional)
boswell wait int_abc123 --timeout 15

# 6. Check status
boswell status int_abc123

# 7. Export when complete
boswell export int_abc123 --output ./interviews/governance-interview/
```

## Architecture

```
                          BOSWELL CLI
     boswell create | status | wait | export | retry | list
                              |
                    BOSWELL CORE (Python)
     +-------------------------------------------------+
     | - Interview lifecycle management                 |
     | - Research ingestion (docs + URLs -> Claude)     |
     | - Dynamic conversation logic                     |
     | - Output pipeline (transcript -> insights)       |
     +-------------------------------------------------+
                              |
                   EXTERNAL SERVICES
     +-------------------------------------------------+
     | Pipecat          | Voice agent framework        |
     | MeetingBaaS      | Bot dispatch to meetings     |
     | ElevenLabs       | Text-to-speech               |
     | Deepgram         | Speech-to-text               |
     | Claude API       | Question gen & conversation  |
     +-------------------------------------------------+
```

### Module Overview

| Module | Purpose |
|--------|---------|
| `cli.py` | Command-line interface using Typer |
| `config.py` | Configuration management (~/.boswell/config.json) |
| `interview.py` | Interview model and lifecycle management |
| `ingestion.py` | Research processing and question generation |
| `meeting.py` | MeetingBaaS integration for bot dispatch |
| `conversation.py` | Dynamic conversation engine |
| `output.py` | Transcript cleanup and insight extraction |

## Interview States

```
PENDING ─────────────────┐
    │                    │
    ▼                    │ (retry)
WAITING ─────────────────┤
    │                    │
    ├───────┬───────┐    │
    ▼       ▼       ▼    │
IN_PROGRESS NO_SHOW ERROR
    │          │       │
    ▼          └───────┘
PROCESSING
    │
    ▼
COMPLETE
```

## Output Format

### transcript.md

```markdown
---
interview_id: int_7x8f2k
guest: Jane Smith
date: 2024-01-22
duration: 32min
topic: AI safety research
---

# Interview Transcript

**Boswell:** Tell me about your path into AI safety...

**Jane:** I started in theoretical physics, actually...
```

### insights.md

```markdown
# Key Insights

## Theme 1: From Physics to AI Safety
Jane's transition from physics gave her a unique lens...
> "The problems felt similar - you're reasoning about systems
> you can't fully observe" (4:32)

## Theme 2: The Alignment Problem
She believes public discourse undersells the difficulty...

## Notable Quotes
> "We're not even sure what the right questions are yet" (12:15)

## Summary
[2-3 paragraph overview]
```

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=boswell
```

### Linting

```bash
# Check linting
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Voice Framework | Pipecat |
| Meeting Integration | MeetingBaaS Speaking Bots API |
| Text-to-Speech | ElevenLabs |
| Speech-to-Text | Deepgram |
| LLM | Claude API (claude-sonnet-4) |
| CLI | Typer |
| Validation | Pydantic |
| HTTP Client | httpx |

## External Service Costs

| Service | Purpose | Billing |
|---------|---------|---------|
| Claude API | Question generation, conversation, analysis | Per token |
| ElevenLabs | AI interviewer voice | Per character |
| Deepgram | Real-time transcription | Per minute |
| MeetingBaaS | Meeting room creation, bot dispatch | Per meeting |

Users bring their own API keys.

## License

MIT

## References

- [Pipecat](https://github.com/pipecat-ai/pipecat) - Voice agent framework
- [MeetingBaaS](https://meetingbaas.com) - Meeting bot infrastructure
- [ElevenLabs](https://elevenlabs.io) - Text-to-speech API
- [Deepgram](https://deepgram.com) - Speech-to-text API
- [Anthropic Claude](https://anthropic.com) - LLM API
