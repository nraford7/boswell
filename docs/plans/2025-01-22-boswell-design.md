# Boswell: AI Research Interviewer

An open-source AI interviewer that joins Zoom/Meet calls, conducts research-informed interviews autonomously, and outputs structured transcripts and insights.

## Problem

Commercial AI interview tools (Outset, Conveo, Listen Labs) are expensive, closed-source, and designed for market research at scale. There's no open-source solution for journalists and researchers who need:

- AI that joins existing video call infrastructure (Zoom/Meet)
- Research-informed question generation from documents and URLs
- Dynamic, human-like conversation (not scripted Q&A)
- Full content pipeline from recording to publishable insights

## Solution

Boswell conducts autonomous interviews. Researcher provides topic + research materials, gets a meeting link, sends it to guest. AI handles the rest.

## Core Flow

```
1. Researcher: boswell create --topic "..." --docs ./research/
2. System: Ingests docs, generates questions, returns meeting link
3. Guest: Joins meeting, AI interviewer is waiting
4. AI: Conducts dynamic 30-minute interview
5. System: Processes recording into transcript + insights
6. Researcher: boswell export → gets markdown files
```

## Key Decisions

| Aspect | Decision |
|--------|----------|
| Delivery | Guest-only Zoom/Meet room, AI waiting |
| Setup | Minimal: topic + docs → link |
| Researcher involvement | Fire and forget, check status after |
| Conversation style | Fully dynamic, follows interesting threads |
| Pacing | AI decides when done, respects max time, periodic guest check-ins |
| Research inputs | Text docs + URL scraping, passed directly to Claude |
| Outputs | Markdown files: transcript.md, insights.md, raw audio |
| Deployment | Docker + CLI, self-hosted, bring your own API keys |
| Voice | Neutral professional (NPR interviewer style) |
| Errors | Graceful degradation + logging |
| Consent | Researcher responsibility, tool provides templates |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         BOSWELL CLI                              │
│  boswell create | boswell status | boswell export               │
└─────────────────────┬───────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                    BOSWELL CORE (new code)                       │
│  - Interview lifecycle management                                │
│  - Research ingestion (docs + URLs → Claude)                    │
│  - Dynamic conversation logic                                    │
│  - Output pipeline (transcript → insights)                      │
└──────┬──────────────────────────────────────────────────────────┘
       │
       │ extends/uses
       ▼
┌─────────────────────────────────────────────────────────────────┐
│              EXISTING OPEN SOURCE                                │
├─────────────────────────────────────────────────────────────────┤
│  Pipecat              │  Voice agent framework                   │
│  speaking-meeting-bot │  Join Meet/Teams, speak, listen          │
│  MeetingBaaS API      │  Meeting room creation, bot dispatch     │
│  ElevenLabs           │  TTS (interviewer voice)                 │
│  Deepgram             │  STT (guest transcription)               │
│  Claude API           │  Question gen, conversation, analysis    │
└─────────────────────────────────────────────────────────────────┘
```

### What We Build (~40%)

- CLI and orchestration
- Research ingestion (pass docs/URLs to Claude)
- Question generation prompt
- Interview conversation logic (one Claude call per turn)
- Guest check-in logic
- No-show timeout handling
- Output processing (two Claude calls: clean transcript, extract insights)

### What We Leverage (~60%)

- Pipecat: Voice agent framework
- speaking-meeting-bot: Meeting join, voice I/O, turn-taking
- MeetingBaaS: Meeting room creation
- ElevenLabs: Text-to-speech
- Deepgram: Speech-to-text with speaker diarization

## Research Ingestion

No vector DB. No embeddings. No LlamaIndex.

```
┌──────────────┐     ┌──────────────┐
│   Raw Input  │────▶│   Claude     │
│              │     │              │
├──────────────┤     │ "Here are    │
│ PDFs         │     │  docs about  │
│ URLs         │     │  the guest.  │
│ Text files   │────▶│  Generate    │
│              │     │  interview   │
└──────────────┘     │  questions." │
                     └──────────────┘
```

Claude reads PDFs and web pages natively. Pass the content directly, get questions back. If research materials exceed context limits, tell the user to curate their inputs.

## Conversation Logic

No graph structures. No scoring algorithms. Let Claude decide each turn.

```python
def next_turn(state, guest_response):
    prompt = f"""You're a skilled interviewer conducting a research interview.

    Prepared questions not yet asked:
    {state.not_asked}

    The guest just said:
    "{guest_response}"

    Time remaining: {state.time_remaining}

    What's the most natural next move?
    - Follow an interesting thread they opened?
    - Connect to one of your unasked questions?
    - Loop back to something you skipped earlier?
    - Check in on the guest's time/energy?
    - Begin wrapping up?

    Respond with just your next question or comment."""

    return claude.complete(prompt)
```

The interviewer "skill" lives in the prompt, not in code.

### Guest Check-ins

Every ~5 questions:
```
"How are we doing on time? Should we keep going,
or is there anything you'd like to make sure we cover?"
```

### Wrap-up Triggers

- All key topics covered
- Approaching max_time
- Guest signals time pressure
- Guest explicitly ends

### No-Show Handling

- Guest hasn't joined after 10 minutes
- Bot leaves meeting
- Status set to "no_show"
- `boswell retry` generates new link

## Output Pipeline

Three files. Markdown only.

```
boswell/outputs/2024-01-22-guest-name/
├── transcript.md
├── insights.md
└── raw/
    └── audio.wav
```

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

## Theme 2: The Alignment Problem is Understated
She believes public discourse undersells the difficulty...
> "We're not even sure what the right questions are yet" (12:15)

## Theme 3: Unexpected Take on Regulation
Surprisingly skeptical of current regulatory approaches...
> "You can't regulate what you don't understand" (24:08)
```

### Processing Steps

1. **Transcript cleanup**: Raw Deepgram → clean, readable markdown with speaker labels
2. **Insight extraction**: Transcript → themes, key quotes, timestamps

Two Claude calls. Write files to disk.

## CLI Interface

```bash
# Setup (one-time)
boswell init
# Prompts for API keys: Claude, ElevenLabs, Deepgram
# Stores in ~/.boswell/config.json

# Create interview
boswell create \
  --topic "AI safety research" \
  --docs ./research/ \
  --urls https://guest-bio.com, https://their-paper.pdf

# Returns:
# ✓ Processed 3 documents, 2 URLs
# ✓ Generated 12 questions
# ✓ Interview ready
#
# Share this link with your guest:
# https://meet.google.com/abc-defg-hij
#
# Interview ID: int_7x8f2k

# Check status
boswell status int_7x8f2k
# → waiting | in_progress | processing | complete | no_show

# Retry after no-show
boswell retry int_7x8f2k
# → Generates new meeting link

# Get outputs
boswell export int_7x8f2k --output ./interviews/

# List past interviews
boswell list
```

### Config (~/.boswell/config.json)

```json
{
  "claude_api_key": "sk-...",
  "elevenlabs_api_key": "...",
  "deepgram_api_key": "...",
  "meeting_provider": "google_meet",
  "default_target_time": 30,
  "default_max_time": 45
}
```

## Deployment

Docker Compose. Self-hosted. Bring your own API keys.

```bash
git clone https://github.com/yourname/boswell
cd boswell
cp .env.example .env  # Add API keys
docker-compose up -d
boswell init
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Voice framework | Pipecat |
| Meeting bot | speaking-meeting-bot / MeetingBaaS |
| TTS | ElevenLabs |
| STT | Deepgram |
| LLM | Claude API |
| CLI | Python (Click or Typer) |
| Container | Docker |

## Dependencies (External Services)

| Service | Purpose | Cost Model |
|---------|---------|------------|
| Claude API | Question gen, conversation, analysis | Per token |
| ElevenLabs | AI interviewer voice | Per character |
| Deepgram | Transcription | Per minute |
| MeetingBaaS | Meeting room creation | Per meeting |

Users bring their own API keys. No cost to project maintainers.

## What Boswell Is Not

- Not a market research tool (use Outset/Conveo for that)
- Not a job interview tool (use FoloUp for that)
- Not a podcast recorder (use Riverside/Descript for that)

Boswell is for researchers and journalists who need to conduct substantive interviews at scale without losing the human touch.

## Open Questions

1. **Zoom support**: speaking-meeting-bot supports Meet/Teams. Zoom may require additional work or Recall.ai integration.
2. **MeetingBaaS pricing**: Need to verify their API access and costs.
3. **Voice selection**: Start with one neutral voice, or let researchers choose from ElevenLabs library?

## Future Considerations (v2)

- Notifications (email/webhook when interview completes)
- Test mode (dry run without real meeting)
- Cost tracking per interview
- iOS app for in-person field interviews
- Multiple interviewer personas

## References

- [Pipecat](https://github.com/pipecat-ai/pipecat) - Voice agent framework
- [speaking-meeting-bot](https://github.com/Meeting-Baas/speaking-meeting-bot) - AI meeting agents
- [MeetingBaaS](https://meetingbaas.com) - Meeting bot infrastructure
- [Outset](https://outset.ai) - Commercial AI interview platform (reference)
- [Conveo](https://conveo.ai) - Commercial AI interview platform (reference)
