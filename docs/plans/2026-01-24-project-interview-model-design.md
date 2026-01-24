# Project vs Interview Model Redesign

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate Project (research container) from Interview (personalized conversation instance), enabling both generic public interviews and highly personalized invite-based interviews.

**Architecture:** Projects define research goals, base questions, and general context. Interviews belong to projects and contain person-specific information that Boswell uses to personalize the conversation.

**Tech Stack:** SQLAlchemy models, Alembic migrations, FastAPI routes, Jinja2 templates, Pipecat voice pipeline.

---

## Core Concepts

### Project = Research Container
- **Name**: Display title (e.g., "Q1 Customer Research")
- **Topic**: Research intent/goals (contextual metadata)
- **Research materials**: Links, files, background for ALL interviews
- **Base questions**: Core questions to explore
- **Public link**: Optional reusable link for anonymous interviews

### Interview = Personalized Conversation Instance
- **Interviewee name**: The person being interviewed
- **Email**: Optional (for sending invites)
- **Context materials**: Links, files, notes about THIS person
- **Transcript & Analysis**: Output of the conversation

### Boswell's Runtime Behavior
1. Read project's base questions and research
2. Read interview's personalized context (if available)
3. Synthesize: Ask project questions customized to this person's context

---

## Data Model Changes

### Project (updated)
```
Project
├── id
├── name              ← NEW: display title
├── topic             ← research intent/goals
├── questions         ← base questions (JSONB)
├── research_summary  ← processed text from materials
├── research_links    ← NEW: URLs for project context (JSONB array)
├── target_minutes
├── public_link_token
├── team_id, template_id, created_by, created_at
└── interviews[]
```

### Interview (updated)
```
Interview
├── id
├── project_id
├── name              ← interviewee's name
├── email             ← optional
├── bio_url           ← existing
├── context_notes     ← NEW: free-text background on this person
├── context_links     ← NEW: URLs about this person (JSONB array)
├── status, room_name, room_token
├── magic_token
├── invited_at, started_at, completed_at, expires_at
├── transcript
└── analysis
```

---

## UI Flows

### Project Creation (redesigned)
No person info. Just the research container.

```
┌─────────────────────────────────────────┐
│ New Project                             │
├─────────────────────────────────────────┤
│ PROJECT DETAILS                         │
│ ├─ Name*: [Q1 Customer Research      ]  │
│ ├─ Topic*: [Understanding customer      │
│ │          pain points with onboarding] │
│ └─ Duration: [30] minutes               │
├─────────────────────────────────────────┤
│ RESEARCH MATERIALS (optional)           │
│ ├─ Upload Documents: [PDFs, docs...]    │
│ └─ Web Links: [URLs to scrape]          │
├─────────────────────────────────────────┤
│ INTERVIEW QUESTIONS (optional)          │
│ └─ [Questions textarea or generate]     │
├─────────────────────────────────────────┤
│           [Create Project]              │
└─────────────────────────────────────────┘
```

### Interview Creation (within a project)
Person info plus their background materials.

```
┌─────────────────────────────────────────┐
│ Add Interview to "Q1 Customer Research" │
├─────────────────────────────────────────┤
│ INTERVIEWEE                             │
│ ├─ Name*: [Steve Johnson             ]  │
│ └─ Email: [steve@widgetcorp.com      ]  │
│           (optional - for sending invite)│
├─────────────────────────────────────────┤
│ BACKGROUND ON THIS PERSON (optional)    │
│ ├─ Notes: [VP of Ops at WidgetCorp,     │
│ │         manufacturing, 2yr customer]  │
│ ├─ Links: [LinkedIn, company page...]   │
│ └─ Files: [Bio, past notes...]          │
├─────────────────────────────────────────┤
│     [Create & Send Invite]              │
│     [Create Interview Only]             │
└─────────────────────────────────────────┘
```

### Dashboard Cards (updated)
Show project NAME as title, not topic.

```
┌────────────────────────────────┐
│ Q1 Customer Research      ← NAME
│ 30 min · Created Jan 24       │
│ 5 Interviews | 3 Done | 2 Pending │
└────────────────────────────────┘
```

### Public Link Flow (unchanged)
- Person enters name only
- No personalization materials
- Uses project-level context only

---

## Interview Types

| Type | Project Context | Interview Context | Result |
|------|-----------------|-------------------|--------|
| **Invite** (personalized) | ✓ | ✓ | Tailored questions based on person's background |
| **Public link** | ✓ | Name only | Generic questions, addressed by name |

---

## Implementation Tasks

### 1. Database Migration
- Add `name` field to Project (interviews table)
- Add `research_links` (JSONB) to Project
- Add `context_notes` (Text) to Interview (guests table)
- Add `context_links` (JSONB) to Interview

### 2. Update Models
- Add new fields to Project and Interview classes
- Update relationships if needed

### 3. Redesign Project Creation
- Update `project_new.html`: Remove person fields, add `name` field
- Update `POST /admin/projects/new`: Create project without interview
- Handle research materials (links, files) at project level

### 4. Update Dashboard
- Update `dashboard.html`: Show `project.name` as card title

### 5. Update Project Detail/Edit
- Update `project_detail.html`: Show name as title, topic as metadata
- Update `project_edit.html`: Allow editing name and topic separately

### 6. Create Interview Creation Flow
- New template `interview_new.html`: Person info + background materials
- New route `POST /admin/projects/{id}/interviews/new`
- Update project detail to list interviews with "Add Interview" button

### 7. Update Voice Pipeline
- Modify `build_system_prompt()` to accept interview context
- Update `worker.py` to fetch and pass interview context
- Personalize questions when interview context is available

### 8. Update Existing Routes
- Ensure invite flow uses interview-level context
- Update transcript/analysis views if needed

---

## Design Decisions

- **Duration at project level only**: Simpler mental model. Different durations = different projects.
- **Public link at project level**: Creates new interviews within the project. Already implemented.
- **File processing**: Existing scraping logic works for both project and interview materials.
