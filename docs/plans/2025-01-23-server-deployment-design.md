# Boswell Server Deployment Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Transform Boswell from a CLI tool into a web application with admin dashboard, guest self-service, and interview management.

**Architecture:** Two-container deployment on Railway - a web API (FastAPI + HTMX) handling admin/guest interfaces and background jobs, plus a voice bot worker running Pipecat pipelines. PostgreSQL for persistence with JSONB for transcripts (pgvector-ready for future AI training).

**Tech Stack:** FastAPI, HTMX, Jinja2, PostgreSQL, Pipecat, Daily.co, Resend

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        BOSWELL SERVER                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌───────────────────────────┐    ┌─────────────────────┐     │
│   │  Container 1: Web         │    │  Container 2: Voice │     │
│   │  ├── FastAPI (API)        │    │  └── Pipecat Worker │     │
│   │  ├── Admin Dashboard      │    │      (long-running) │     │
│   │  ├── Guest Pages          │    │                     │     │
│   │  └── Background Jobs      │    │                     │     │
│   └─────────────┬─────────────┘    └──────────┬──────────┘     │
│                 │                              │                 │
│                 └──────────────┬───────────────┘                 │
│                                │                                 │
│                       ┌────────▼────────┐                       │
│                       │   PostgreSQL    │                       │
│                       │   (+ JSONB)     │                       │
│                       └─────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘

External Services: Daily.co, Deepgram, ElevenLabs, Claude, Resend
```

---

## 2. Data Model

### 2.1 Team & User (Admin Auth)

```sql
CREATE TABLE team (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE "user" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID REFERENCES team(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 2.2 Interview Template

```sql
CREATE TABLE interview_template (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID REFERENCES team(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,           -- "Deep Dive", "Quick Pulse"
    description TEXT,
    prompt_modifier TEXT,                  -- Style tweaks for system prompt
    default_minutes INTEGER DEFAULT 30,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Example templates:**
- "Deep Dive Research" - 45 min, exploratory
- "Quick Pulse Check" - 10 min, focused
- "Expert Interview" - 30 min, technical depth
- "Oral History" - 60 min, narrative style

### 2.3 Interview

```sql
CREATE TABLE interview (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID REFERENCES interview_template(id),
    team_id UUID REFERENCES team(id) ON DELETE CASCADE,
    topic VARCHAR(500) NOT NULL,
    questions JSONB,                       -- Generated questions array
    research_summary TEXT,
    target_minutes INTEGER DEFAULT 30,
    created_by UUID REFERENCES "user"(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 2.4 Guest

```sql
CREATE TABLE guest (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interview_id UUID REFERENCES interview(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    bio_url TEXT,                          -- Optional research source
    magic_token VARCHAR(64) UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'invited',  -- invited/started/completed/expired
    room_name VARCHAR(255),                -- Daily.co room for rejoin
    invited_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE    -- Magic link expiry
);

CREATE INDEX idx_guest_magic_token ON guest(magic_token);
CREATE INDEX idx_guest_status ON guest(status);
```

### 2.5 Transcript

```sql
CREATE TABLE transcript (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_id UUID REFERENCES guest(id) ON DELETE CASCADE,
    entries JSONB NOT NULL,                -- Full transcript with timestamps
    conversation_context JSONB,            -- For pause/resume
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**entries JSONB structure:**
```json
[
  {
    "timestamp": "2025-01-23T10:30:00Z",
    "speaker": "guest",
    "text": "I think the key insight was...",
    "struck": false
  },
  {
    "timestamp": "2025-01-23T10:30:15Z",
    "speaker": "boswell",
    "text": "That's fascinating. Can you elaborate?"
  }
]
```

### 2.6 Analysis

```sql
CREATE TABLE analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_id UUID REFERENCES guest(id) ON DELETE CASCADE,
    insights JSONB,                        -- Structured extraction
    summary_md TEXT,                       -- Human-readable markdown
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 3. User Flows

### 3.1 Admin: Create Interview (Single Guest)

```
1. Log into dashboard
2. Click "New Interview"
3. Select template (e.g., "Deep Dive Research")
4. Enter topic
5. Upload research docs or enter URLs
6. System generates questions (Claude)
7. Review/edit questions
8. Click "Invite Guest"
9. Enter guest email + name + optional bio URL
10. System sends magic link email
```

### 3.2 Admin: Bulk Import

```
1. Click "Bulk Import"
2. Upload CSV with columns:
   - email (required)
   - name (required)
   - bio_url (optional)
   - topic (optional, overrides shared topic)
3. Select template
4. Enter shared topic (or check "use topic column")
5. Enter shared research docs/URLs (optional)
6. Click "Create & Send"
7. System queues for each row:
   - Create Interview (if per-guest topic) or link to shared Interview
   - Create Guest record
   - Generate questions (using bio_url if provided)
   - Send invite email
8. Dashboard shows batch progress
```

**CSV example:**
```csv
email,name,bio_url,topic
alice@example.com,Alice Smith,https://linkedin.com/in/alice,
bob@example.com,Bob Jones,https://bob.com/bio,Future of robotics
carol@example.com,Carol White,,
```

### 3.3 Guest: Take Interview

```
1. Receive email: "You're invited to an interview about {topic}"
2. Click magic link → landing page shows:
   - Topic and expected duration
   - Privacy: anonymous by default, transcript emailed after
   - Can say "forget that" to strike content
   - Can pause/stop/ask for repeats
3. Click "Start Interview"
4. Daily.co room opens, bot joins
5. Interview proceeds (existing Pipecat flow)
6. On completion:
   - "Thank you" page displayed
   - Transcript emailed to guest
   - Analysis generated in background
```

### 3.4 Guest: Rejoin

```
Guest clicks magic link while interview in progress:

status == 'invited':
  → Show landing page, "Start Interview" button
  → On click: create Daily room, set status='started', store room_name

status == 'started' AND room still active:
  → Show "Rejoin Interview" page
  → On click: connect to existing room_name
  → Bot welcomes them back, continues from context

status == 'started' AND room expired:
  → Show "Session expired" page
  → Option to request new link from admin

status == 'completed':
  → Show "Thank you" page
  → Link to download transcript

status == 'expired' (past expires_at):
  → Show "Link expired" page
  → Contact info for admin
```

### 3.5 Admin: Monitor & Download

```
Dashboard shows:
- Interview list with filters (template, status, date)
- Each interview shows guests and their status
- Click guest → view transcript, analysis
- Download options:
  - Markdown (human-readable)
  - JSON (structured)
  - Training export (filtered, formatted for AI)
- Bulk actions: resend invites, extend expiry
```

---

## 4. API Endpoints

### 4.1 Auth

```
POST /api/auth/login          - Send magic link to admin email
GET  /api/auth/verify/{token} - Verify magic link, set session
POST /api/auth/logout         - Clear session
```

### 4.2 Templates

```
GET    /api/templates              - List team's templates
POST   /api/templates              - Create template
GET    /api/templates/{id}         - Get template
PUT    /api/templates/{id}         - Update template
DELETE /api/templates/{id}         - Delete template
```

### 4.3 Interviews

```
GET    /api/interviews             - List interviews (with filters)
POST   /api/interviews             - Create interview
GET    /api/interviews/{id}        - Get interview with guests
PUT    /api/interviews/{id}        - Update interview
DELETE /api/interviews/{id}        - Delete interview
POST   /api/interviews/bulk        - Bulk create from CSV
```

### 4.4 Guests

```
GET    /api/interviews/{id}/guests     - List guests for interview
POST   /api/interviews/{id}/guests     - Add guest (sends invite)
GET    /api/guests/{id}                - Get guest details
DELETE /api/guests/{id}                - Remove guest
POST   /api/guests/{id}/resend         - Resend invite email
POST   /api/guests/{id}/extend         - Extend expiry
```

### 4.5 Transcripts & Analysis

```
GET /api/guests/{id}/transcript        - Get transcript
GET /api/guests/{id}/transcript.md     - Download as markdown
GET /api/guests/{id}/transcript.json   - Download as JSON
GET /api/guests/{id}/analysis          - Get analysis
POST /api/guests/{id}/analysis/regenerate - Regenerate analysis
```

### 4.6 Internal (Voice Worker)

```
GET  /api/internal/pending-interviews  - Poll for guests ready to start
POST /api/internal/claim/{guest_id}    - Claim interview (lock)
POST /api/internal/transcript/{guest_id} - Save transcript
POST /api/internal/complete/{guest_id} - Mark complete
```

---

## 5. Page Routes

### 5.1 Admin Dashboard

```
GET /admin/login              - Login page
GET /admin/                   - Dashboard home (interview list)
GET /admin/interviews/new     - Create interview form
GET /admin/interviews/{id}    - Interview detail (guests, status)
GET /admin/interviews/import  - Bulk import page
GET /admin/templates          - Template management
GET /admin/templates/new      - Create template form
GET /admin/templates/{id}     - Edit template
```

### 5.2 Guest Pages

```
GET /i/{magic_token}          - Guest landing / rejoin / thank you
POST /i/{magic_token}/start   - Start interview (creates room)
GET /i/{magic_token}/room     - Interview room page (embeds Daily)
```

---

## 6. Background Jobs

### 6.1 Job Types

```python
class JobType(Enum):
    GENERATE_QUESTIONS = "generate_questions"
    SEND_INVITE_EMAIL = "send_invite_email"
    SEND_TRANSCRIPT_EMAIL = "send_transcript_email"
    GENERATE_ANALYSIS = "generate_analysis"
    EXPIRE_GUESTS = "expire_guests"  # Scheduled, marks expired links
```

### 6.2 Job Queue (Simple Postgres)

```sql
CREATE TABLE job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- pending/processing/completed/failed
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    run_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_job_queue_pending ON job_queue(status, run_at)
    WHERE status = 'pending';
```

### 6.3 Worker Loop

```python
async def process_jobs():
    while True:
        job = await db.fetch_one("""
            UPDATE job_queue
            SET status = 'processing', started_at = NOW(), attempts = attempts + 1
            WHERE id = (
                SELECT id FROM job_queue
                WHERE status = 'pending' AND run_at <= NOW()
                ORDER BY run_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        """)

        if job:
            try:
                await handle_job(job)
                await mark_completed(job.id)
            except Exception as e:
                await mark_failed(job.id, str(e))
        else:
            await asyncio.sleep(2)
```

---

## 7. Voice Worker

### 7.1 Coordination

Voice worker polls for interviews where guest has clicked "Start":

```python
async def poll_for_interviews():
    while True:
        guest = await claim_pending_interview()
        if guest:
            await run_interview(guest)
        else:
            await asyncio.sleep(2)

async def claim_pending_interview():
    """Claim an interview atomically to prevent double-processing."""
    return await db.fetch_one("""
        UPDATE guest
        SET claimed_by = $1, claimed_at = NOW()
        WHERE id = (
            SELECT id FROM guest
            WHERE status = 'started'
              AND claimed_by IS NULL
              AND room_name IS NOT NULL
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
    """, worker_id)
```

### 7.2 Interview Lifecycle

```python
async def run_interview(guest):
    # Load interview details
    interview = await get_interview(guest.interview_id)
    template = await get_template(interview.template_id)

    # Build system prompt (existing logic + template modifier)
    system_prompt = build_system_prompt(
        topic=interview.topic,
        questions=interview.questions,
        prompt_modifier=template.prompt_modifier,
        target_minutes=interview.target_minutes,
    )

    # Get existing context if rejoin
    transcript_record = await get_transcript(guest.id)
    initial_messages = transcript_record.conversation_context if transcript_record else None

    # Run Pipecat pipeline (existing code)
    transcript, context = await run_interview(
        room_url=f"https://daily.co/{guest.room_name}",
        room_token=guest.room_token,
        system_prompt=system_prompt,
        initial_messages=initial_messages,
    )

    # Save transcript
    await save_transcript(guest.id, transcript, context)

    # Mark complete and queue follow-up jobs
    await mark_guest_complete(guest.id)
    await queue_job(JobType.SEND_TRANSCRIPT_EMAIL, {"guest_id": guest.id})
    await queue_job(JobType.GENERATE_ANALYSIS, {"guest_id": guest.id})
```

---

## 8. Email Templates

### 8.1 Invite Email

```
Subject: You're invited to an interview about {topic}

Hi {name},

{inviter_name} from {team_name} has invited you to a recorded interview.

Topic: {topic}
Expected duration: {minutes} minutes

This interview is anonymous by default - your name won't be associated
with it unless you choose. You'll receive a full transcript by email
right after the interview.

During the interview, you can:
- Ask to pause, stop, or repeat any question
- Say "forget that" to remove anything from the record

[Start Interview Button] → {magic_link}

This link expires on {expires_at}.

Questions? Reply to this email.
```

### 8.2 Transcript Email

```
Subject: Your interview transcript - {topic}

Hi {name},

Thank you for participating in the interview about {topic}.

Your transcript is attached. If you'd like anything removed or have
questions, just reply to this email.

Best,
{team_name}

[Attachment: transcript.md]
```

---

## 9. Deployment

### 9.1 Railway Setup

```
Project: boswell
├── Service: boswell-web
│   ├── Dockerfile (FastAPI app)
│   ├── Port: 8000
│   └── Public URL: interviews.yourdomain.com
├── Service: boswell-voice
│   ├── Dockerfile (voice worker)
│   └── No public port (internal only)
└── Database: PostgreSQL (Railway add-on)
```

### 9.2 Environment Variables

```bash
# Database
DATABASE_URL=postgresql://...

# External Services
DAILY_API_KEY=...
CLAUDE_API_KEY=...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
RESEND_API_KEY=...

# App Config
SECRET_KEY=...              # For signing tokens
BASE_URL=https://interviews.yourdomain.com
ADMIN_EMAILS=you@example.com,teammate@example.com  # Allowed admins

# Voice Worker
WORKER_ID=worker-1          # Unique per instance
```

### 9.3 Dockerfiles

**boswell-web:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "boswell.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**boswell-voice:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "boswell.server.voice_worker"]
```

---

## 10. Security

### 10.1 Admin Auth

- Magic link to whitelisted admin emails (ADMIN_EMAILS env var)
- Session stored in secure HTTP-only cookie
- Sessions expire after 7 days

### 10.2 Guest Auth

- Magic token: 64-character random string
- Stored hashed in database
- Single-use: can rejoin while status='started', but link dies after complete
- Expires after N days (configurable, default 7)

### 10.3 Voice Worker

- Internal API endpoints require shared secret header
- Worker claims interviews atomically (prevents double-processing)

---

## 11. Future Enhancements (Out of Scope)

- **Contact Pool**: Persistent contact management with tags
- **CRM Integration**: Direct HubSpot/Airtable sync
- **pgvector**: Embedding storage for semantic search
- **Training Exports**: Specialized formats for fine-tuning
- **Rich Dashboard**: React frontend with real-time updates
- **Multi-tenant**: Organization isolation, billing
- **Recording Playback**: Store and replay audio

---

## 12. Success Criteria

1. Admin can create interview from template + topic + research
2. Admin can bulk import CSV and send invites
3. Guests receive magic link, click to start interview
4. Guests can rejoin if disconnected
5. Transcripts saved and emailed automatically
6. Analysis generated after completion
7. Admin can view status, download transcripts
8. Deploys to Railway with zero-downtime updates
