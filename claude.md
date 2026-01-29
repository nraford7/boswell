# Boswell

AI research interviewer that conducts autonomous, voice-based interviews from research materials.

## Purpose

Boswell enables researchers, authors, and journalists to conduct substantive interviews at scale. Key capabilities:

- **Research ingestion**: Process PDFs, documents, and URLs to generate interview questions via Claude
- **Real-time voice interviews**: Dynamic conversations using Daily.co rooms, Deepgram STT, and ElevenLabs TTS
- **Interview angles**: Five styles (Exploratory, Interrogative, Imaginative, Documentary, Coaching)
- **Pause & resume**: Stop interviews mid-way and continue with full context
- **Dynamic controls**: Speed adjustment, "strike from record" functionality
- **Templates**: Reusable interview configurations across multiple guests

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+, FastAPI 0.109+, SQLAlchemy 2.0+ (async) |
| Database | PostgreSQL 15+ with asyncpg, Alembic migrations |
| Voice Pipeline | Pipecat-AI 0.0.100+ |
| Audio Transport | Daily.co WebRTC |
| STT | Deepgram Nova-2 |
| TTS | ElevenLabs Turbo v2 (Rachel voice) |
| LLM | Claude Sonnet 4 |
| Frontend | React 18, TypeScript, Vite, @daily-co/daily-react |
| Deployment | Docker multi-stage, docker-compose |

## Architecture

```
boswell/
├── src/boswell/
│   ├── cli.py                 # Local CLI interface
│   ├── ingestion.py           # Document processing & question generation
│   ├── voice/
│   │   ├── pipeline.py        # Pipecat voice pipeline setup
│   │   ├── bot.py             # Interview bot lifecycle
│   │   ├── prompts.py         # System prompts with interview angles
│   │   ├── transcript.py      # Real-time transcript collection
│   │   ├── acknowledgment.py  # Natural pacing ("Mm-hmm", "I see")
│   │   ├── speed_control.py   # Dynamic TTS speed adjustment
│   │   └── strike_control.py  # "Forget that" functionality
│   └── server/
│       ├── main.py            # FastAPI app + lifespan
│       ├── models.py          # SQLAlchemy ORM models
│       ├── worker.py          # Voice worker (polls DB, runs interviews)
│       ├── routes/
│       │   ├── admin.py       # Admin dashboard
│       │   └── guest.py       # Public interview routes
│       └── migrations/        # Alembic migrations
├── room-ui/                   # React frontend for Daily.co rooms
│   └── src/components/
│       └── Room.tsx           # Main room view with audio gate
└── docker-compose.yml
```

### Services

1. **Web Service**: FastAPI serving admin dashboard and guest pages
2. **Voice Worker**: Separate process polling database for interviews to start
3. **Room UI**: React app embedded in Daily.co room for guest interface

### Voice Pipeline Flow

```
Daily.co Transport → Deepgram STT → TranscriptCollector
    → AcknowledgmentProcessor → Claude LLM Context
    → StrikeControlProcessor → SpeedControlProcessor
    → ElevenLabs TTS → Daily.co Transport
```

## Database Models

| Model | Table Name | Purpose |
|-------|------------|---------|
| Team | teams | Organization unit |
| User | users | Team members |
| InterviewTemplate | interview_templates | Reusable configuration |
| Project | interviews | Interview collection (legacy naming) |
| Interview | guests | Individual guest interview (legacy naming) |
| Transcript | transcripts | Conversation history + context |
| Analysis | analyses | AI-generated insights |
| JobQueue | job_queue | Background job tracking |

**Interview status lifecycle**: `invited` → `started` → `in_progress` → `completed`

## External Service Integrations

### Daily.co (WebRTC)
- Creates rooms for each interview via Daily API
- Bot joins with `is_owner=True` token
- Guests get restricted tokens
- Files: `server/routes/guest.py`, `voice/bot.py`, `server/worker.py`

### Deepgram (STT)
- Nova-2 model, English
- Real-time transcription in pipeline
- File: `voice/pipeline.py:87-91`

### ElevenLabs (TTS)
- Turbo v2 model, Rachel voice ID: `21m00Tcm4TlvDq8ikWAM`
- Supports speed tags for dynamic adjustment
- File: `voice/pipeline.py:95-99`

### Claude API
- Question generation from research (`ingestion.py`)
- Real-time conversation (`voice/pipeline.py`)
- System prompts with angles (`voice/prompts.py`)
- Model: `claude-sonnet-4-20250514`

### Resend (Email)
- Invitation emails and transcript delivery
- File: `server/email.py`
- Status: Partially implemented (see TODOs)

## Known Issues

### AudioVisualizer Disabled
- **Problem**: ~2 second latency between animation and actual speech
- **Attempted fixes**: `useActiveSpeakerId()`, track property hooks, backend `SpeakingStateProcessor`
- **Root cause**: Buffering and network latency inherent to WebRTC pipeline
- **Status**: Feature disabled in `room-ui/src/components/Room.tsx`

### Pipecat System Prompt Bug
- **Location**: `voice/pipeline.py:124-130`
- **Bug**: `create_context_aggregator()` doesn't copy system parameter from OpenAI context
- **Workaround**: Manually re-set `system` on context after aggregator creation

### Browser Autoplay Policy
- Audio requires user gesture to play
- **Solution**: Click-to-enable audio gate modal in Room.tsx

## Configuration

### Required Environment Variables

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
CLAUDE_API_KEY=sk-ant-...
DAILY_API_KEY=...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
RESEND_API_KEY=...
SECRET_KEY=<32+ char random string>
```

### Optional Variables

```bash
BASE_URL=https://boswell.example.com  # For email links
ADMIN_EMAILS=admin@example.com        # Comma-separated
DAILY_DOMAIN=emirbot                  # Daily.co subdomain
DEBUG=true                            # Debug mode
SQL_ECHO=true                         # Log SQL queries
```

### CLI Config

Location: `~/.boswell/config.json`
Initialize with: `boswell init`

## Development Commands

```bash
# Local development
docker-compose up -d postgres
uv run python -m boswell.server.main    # Start web server
uv run python -m boswell.server.worker  # Start voice worker

# Build room-ui
cd room-ui && npm install && npm run build

# Run migrations
uv run alembic upgrade head

# Tests
uv run pytest
```

## Cost Estimate (per 30-min interview)

| Service | Cost |
|---------|------|
| Daily.co | ~$0.002 |
| Deepgram STT | ~$0.13 |
| ElevenLabs TTS | ~$1.50 |
| Claude LLM | ~$0.50-1.50 |
| **Total** | **~$2-4** |

## Data Flow

1. Admin creates project with research URLs → Claude generates questions
2. Admin adds guests → Interview records created with magic tokens
3. Guest clicks link → Enters Daily.co room
4. Admin starts interview → Worker polls, claims interview, joins bot to room
5. Voice pipeline runs → Transcript collected in real-time
6. Guest leaves → Transcript saved, status → completed
