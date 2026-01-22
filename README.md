# Boswell: AI Research Interviewer

An open-source AI interviewer that conducts research-informed voice interviews autonomously and outputs structured transcripts and insights.

## Overview

Boswell is designed for researchers, authors, and journalists who need to conduct substantive interviews at scale without losing the human touch. You provide a topic and research materials, Boswell generates tailored interview questions, then conducts a real-time voice interview using AI.

**How it works:**
1. Provide a topic and research materials (PDFs, documents, URLs)
2. Boswell generates informed interview questions using Claude
3. Start a voice interview session - Boswell creates a video room you share with your guest
4. The AI conducts a dynamic, conversational interview following interesting threads
5. Export clean transcripts and AI-generated insights

**Key Features:**
- Research-informed question generation from documents and URLs
- Real-time voice interviews with natural conversation flow
- Dynamic follow-up questions that pursue interesting threads
- **Pause & Resume** - Stop interviews and continue later with full context preserved
- **Dynamic Speed Control** - Guests can ask the bot to speak faster or slower
- **Strike from Record** - Guests can say "forget that" to remove content from transcript
- **Privacy First** - Anonymous by default, transcript emailed to guest after
- Immediate acknowledgments ("Mm-hmm", "I see") for natural conversation pacing
- Automatic transcript capture and insight extraction
- Low-latency voice synthesis (~500ms response time)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        BOSWELL CLI                          │
│     boswell create | start | status | export | list         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                     VOICE PIPELINE                          │
│  ┌──────────┐   ┌────────┐   ┌────────┐   ┌────────────┐   │
│  │ Daily.co │──▶│Deepgram│──▶│ Claude │──▶│ ElevenLabs │   │
│  │Transport │   │  STT   │   │  LLM   │   │    TTS     │   │
│  └──────────┘   └────────┘   └────────┘   └────────────┘   │
│       │              │            │             │           │
│       ▼              ▼            ▼             ▼           │
│    [Audio In]   [Transcript]  [Response]   [Audio Out]     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                        │
│  • Daily.co    - WebRTC video rooms                         │
│  • Deepgram    - Speech-to-text (Nova-2)                    │
│  • Claude      - Conversation intelligence (Sonnet 4)       │
│  • ElevenLabs  - Text-to-speech (Turbo v2)                  │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- API keys for: Claude (Anthropic), Daily.co, Deepgram, ElevenLabs

### Installation

```bash
# Clone the repository
git clone https://github.com/noahraford/boswell
cd boswell

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install with voice dependencies
pip install -e ".[voice]"

# Initialize configuration
boswell init
```

### Your First Interview

```bash
# 1. Create an interview with research materials
boswell create --topic "AI Safety Research" --docs ./research/paper.pdf

# 2. Start the voice bot
boswell start int_abc123

# 3. Share the Daily.co room URL with your guest
#    The bot will greet them and conduct the interview

# 4. Export transcript and insights when done
boswell export int_abc123
```

## CLI Commands

### `boswell init`

Initialize Boswell with your API keys.

```bash
boswell init
```

Prompts for:
- **Claude API Key** (required) - For question generation and conversation
- **Deepgram API Key** (required) - For speech-to-text
- **ElevenLabs API Key** (required) - For text-to-speech
- **Daily.co API Key** (required) - For video rooms

### `boswell create`

Create a new interview session with research materials.

```bash
boswell create --topic "Future of Work" --docs ./research.pdf,./notes.md --urls https://guest-bio.com
```

**Options:**
- `--topic, -t` (required): Interview topic
- `--docs, -d`: Comma-separated paths to research documents (PDF, TXT, MD)
- `--urls, -u`: Comma-separated URLs to scrape for research

**What happens:**
1. Ingests and processes research materials
2. Generates tailored interview questions using Claude
3. Creates an interview record ready for voice session

### `boswell start`

Start a voice interview bot.

```bash
boswell start int_abc123
```

**What happens:**
1. Creates a Daily.co video room
2. Starts the Pipecat voice pipeline
3. Bot joins and waits for guest
4. Displays shareable room URL
5. Conducts interview when guest joins
6. Press Ctrl+C to pause - saves conversation context for later
7. Saves transcript when complete

**Output:**
```
Starting voice interview: int_abc123
Topic: AI Safety Research
Questions: 12

Daily.co room created!
==================================================

Send this link to your guest:
  https://yourname.daily.co/boswell-int_abc123

==================================================

Bot is joining the room...
Press Ctrl+C to end the interview.
```

### `boswell resume`

Resume a paused interview with full context preserved.

```bash
boswell resume int_abc123
```

**What happens:**
1. Creates a new Daily.co room
2. Loads conversation history from the paused session
3. Bot welcomes guest back and continues where you left off
4. All previous context is preserved

**Tip:** Pause/resume is useful for:
- Breaking long interviews into multiple sessions
- Handling technical difficulties
- Giving guests time to gather thoughts

### `boswell status`

Check interview status.

```bash
boswell status int_abc123
```

**Statuses:**
- `pending` - Created, not started
- `waiting` - Bot in room, awaiting guest
- `in_progress` - Interview happening
- `paused` - Interview paused, can be resumed
- `complete` - Interview finished
- `error` - Something went wrong

### `boswell export`

Export transcript and insights.

```bash
boswell export int_abc123 --output ./interviews/
```

**Options:**
- `--output, -o`: Output directory
- `--transcript, -t`: Path to external transcript JSON (optional)

**Outputs:**
- `transcript.md` - Clean, formatted interview transcript
- `insights.md` - Key themes, notable quotes, and summary

### `boswell list`

List all interviews.

```bash
boswell list
```

### `boswell retry`

Retry a failed or no-show interview.

```bash
boswell retry int_abc123
```

## Configuration

### Config File

Located at `~/.boswell/config.json`:

```json
{
  "claude_api_key": "sk-ant-...",
  "deepgram_api_key": "...",
  "elevenlabs_api_key": "...",
  "daily_api_key": "...",
  "default_target_time": 30,
  "default_max_time": 45
}
```

### Environment Variables

Alternatively, use a `.env` file:

```bash
CLAUDE_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
DAILY_API_KEY=...
```

## Interview Flow

```
┌─────────────────┐
│  boswell create │  ← Provide topic + research
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Questions      │  ← Claude generates tailored questions
│  Generated      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  boswell start  │  ← Creates Daily.co room
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Share URL      │  ← Guest joins video room
│  with Guest     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Voice          │  ← Real-time conversation
│  Interview      │     Deepgram → Claude → ElevenLabs
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  boswell export │  ← transcript.md + insights.md
└─────────────────┘
```

## The Interview Experience

When your guest joins the Daily.co room:

1. **Greeting** - Boswell introduces itself, explains:
   - The interview topic and expected duration
   - That the interview is anonymous (not attributed unless they want)
   - They'll receive a full transcript via email after
   - They can say "nevermind, forget that" to strike anything from the record
   - They can pause, stop, or ask for repeats anytime
2. **Core Questions** - Works through research-informed questions (one at a time, no sub-questions)
3. **Acknowledgments** - Immediate "Mm-hmm", "I see" responses to show it's listening
4. **Follow-ups** - Pursues interesting threads that emerge naturally
5. **Check-ins** - Periodically asks about time/comfort
6. **Wrap-up** - Thanks guest, asks one time for final thoughts, then goodbye

The AI interviewer is designed to be:
- **Warm and curious** - Like an NPR interviewer
- **Research-informed** - Questions reflect the provided materials
- **Adaptive** - Follows interesting threads rather than rigid scripts
- **Respectful** - Moves on gracefully if guest is uncomfortable
- **Responsive** - Guests can say "slow down" or "speed up" to adjust speech rate
- **Privacy-conscious** - Anonymous by default, with ability to strike content from record

## Output Format

### transcript.md

```markdown
---
interview_id: int_abc123
topic: AI Safety Research
date: 2024-01-22
duration: 28 minutes
---

# Interview Transcript

**Boswell:** Before we get into the specifics, I want to understand
why you first got interested in AI safety. What was the moment or
realization that drew you to this work?

**Guest:** It actually started during my PhD in physics. I was
working on complex systems and started seeing parallels...

**Boswell:** That's fascinating - the connection to complex systems.
Can you say more about what parallels you were seeing?
```

### insights.md

```markdown
# Interview Insights

## Key Themes

### 1. From Physics to AI Safety
The guest's background in complex systems shaped their approach...
> "The problems felt similar - you're reasoning about systems
> you can't fully observe"

### 2. The Coordination Challenge
...

## Notable Quotes

> "We're building systems that will be smarter than us, and we
> don't have a good theory of how to keep them aligned with
> human values"

## Summary

[AI-generated 2-3 paragraph overview]
```

## Project Structure

```
boswell/
├── src/boswell/
│   ├── cli.py           # Command-line interface
│   ├── config.py        # Configuration management
│   ├── interview.py     # Interview model & lifecycle
│   ├── ingestion.py     # Research processing
│   ├── output.py        # Transcript & insights export
│   └── voice/
│       ├── bot.py           # Interview bot lifecycle
│       ├── pipeline.py      # Pipecat voice pipeline
│       ├── prompts.py       # System prompts for Claude
│       ├── transcript.py    # Transcript capture
│       ├── acknowledgment.py # Filler words ("Mm-hmm")
│       ├── speed_control.py  # Dynamic speech rate control
│       └── strike_control.py # "Forget that" content removal
├── tests/
├── docs/
└── pyproject.toml
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev,voice]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
```

## Service Costs

| Service | Purpose | Pricing |
|---------|---------|---------|
| Daily.co | Video rooms | 10k free mins/month, then $0.004/min |
| Deepgram | Speech-to-text | $0.0043/min (Nova-2) |
| ElevenLabs | Text-to-speech | $0.30/1k chars (Turbo) |
| Claude | LLM | $3/$15 per 1M tokens (Sonnet) |

**Estimated cost per 30-min interview:** ~$2-4

## Roadmap

- [x] Research ingestion and question generation
- [x] Real-time voice interviews via Daily.co + Pipecat
- [x] Transcript capture
- [x] Basic export (transcript.md)
- [x] Pause & resume interviews with context preservation
- [x] Dynamic speech speed control (guest can request faster/slower)
- [x] Immediate acknowledgments for natural conversation flow
- [x] Strike from record ("forget that" removes content from transcript)
- [ ] Insights generation with quotes
- [ ] Cloud deployment option
- [ ] Recording and playback
- [ ] Multi-language support

## License

MIT

## Acknowledgments

Built with:
- [Pipecat](https://github.com/pipecat-ai/pipecat) - Voice AI framework
- [Daily.co](https://daily.co) - WebRTC infrastructure
- [Deepgram](https://deepgram.com) - Speech-to-text
- [ElevenLabs](https://elevenlabs.io) - Text-to-speech
- [Anthropic Claude](https://anthropic.com) - LLM

---

*Named after James Boswell, the 18th-century biographer famous for his detailed, conversational biography of Samuel Johnson.*
