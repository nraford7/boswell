# Interview Types & Angles Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable configurable interview styles (angles) that change how Boswell approaches conversations, bundled into reusable Interview Templates that combine content + style.

**Architecture:** Interview Templates define reusable bundles of content (questions, research) and style (angle). Interviews can use a template or define one-off content/style via "Other" option. Person-specific context remains at the interview level.

**Tech Stack:** SQLAlchemy models, Alembic migrations, FastAPI routes, Jinja2 templates, Pipecat voice pipeline.

---

## Core Concepts

### Content vs Style

- **Content**: The "what" — research materials, questions, goals, links, uploaded files
- **Style/Angle**: The "how" — Boswell's stance and approach to the conversation

### Interview Angles (5 presets + custom)

| Angle | Boswell's Stance | Behavior |
|-------|------------------|----------|
| **Exploratory** | Curious learner | Content-directed questions, probes topics from materials, follows tangents briefly then returns |
| **Interrogative** | Constructive skeptic | Challenges claims, asks for evidence, surfaces weaknesses, pushes back respectfully |
| **Imaginative** | Creative collaborator | "What if..." questions, builds on half-formed ideas, explores possibilities |
| **Documentary** | Oral historian | Guest leads narrative, minimal steering, preserves their voice and framing |
| **Coaching** | Reflective facilitator | Socratic method, reflects back, helps guest arrive at their own insights |
| **Custom** | User-defined | Freeform prompt modifier for edge cases |

### Angle Blending

- **Primary angle**: Required, sets the main approach
- **Secondary angle**: Optional, adds a flavor/modifier
- Example: "Mainly exploratory, with some documentary"

### Interview Templates

Reusable bundles of content + style:
- Content: questions, research materials, links, default duration
- Style: primary angle, optional secondary angle
- Users select a template when creating an interview

### Two-Tier UX

1. **Template selection** (normal path): Pick from predefined templates
2. **"Other" option** (power-user): Define one-off content + style inline
   - Optional "Save as template" checkbox to make it reusable

---

## Data Model Changes

### New Enum

```python
class InterviewAngle(str, enum.Enum):
    EXPLORATORY = "exploratory"
    INTERROGATIVE = "interrogative"
    IMAGINATIVE = "imaginative"
    DOCUMENTARY = "documentary"
    COACHING = "coaching"
    CUSTOM = "custom"
```

### InterviewTemplate (updated)

```
InterviewTemplate
├── id
├── team_id
├── name
├── description
├── default_minutes
│
├── questions              ← JSONB, content
├── research_summary       ← processed text from materials
├── research_links         ← JSONB array of URLs
│
├── angle                  ← NEW: InterviewAngle enum (required)
├── angle_secondary        ← NEW: InterviewAngle enum (optional)
├── angle_custom           ← NEW: Text (if angle == CUSTOM)
│
└── created_at
```

### Interview (updated)

```
Interview
├── id
├── project_id
├── name                   ← interviewee name
├── email
├── context_notes          ← about this person
├── context_links          ← JSONB array
│
├── template_id            ← NEW: moved from Project, nullable
│
├── questions              ← NEW: one-off content (overrides template)
├── research_summary       ← NEW: one-off content
├── research_links         ← NEW: one-off content
│
├── angle                  ← NEW: override template's angle
├── angle_secondary        ← NEW: override template's secondary
├── angle_custom           ← NEW: custom prompt if angle == CUSTOM
│
├── status, room_name, room_token
├── magic_token
├── invited_at, started_at, completed_at, expires_at
├── transcript
└── analysis
```

### Project (updated)

```
Project
├── (remove template_id - moves to Interview)
└── (rest unchanged)
```

---

## Prompt Assembly

### Angle Prompts

```python
ANGLE_PROMPTS = {
    "exploratory": """
INTERVIEW APPROACH: Exploratory
- You are learning from the guest about the topic
- Use the research materials and questions to guide the conversation
- Probe deeper on content-relevant areas
- Follow interesting tangents briefly, then return to key topics
- Goal: surface what the guest knows about this subject
""",

    "interrogative": """
INTERVIEW APPROACH: Interrogative
- You are constructively challenging the guest's claims and reasoning
- Ask for evidence, examples, and specifics
- Surface potential weaknesses or counterarguments
- Push back respectfully when claims seem unsupported
- Goal: stress-test ideas and find gaps in thinking
""",

    "imaginative": """
INTERVIEW APPROACH: Imaginative
- You are a creative collaborator helping develop ideas
- Build on half-formed thoughts with "what if..." questions
- Explore possibilities and hypotheticals together
- Help the guest think beyond current constraints
- Goal: expand and develop the guest's thinking
""",

    "documentary": """
INTERVIEW APPROACH: Documentary
- You are capturing the guest's story and perspective
- Let them lead the narrative; follow their thread
- Prepared questions are conversation starters, not a checklist
- Minimize steering; preserve their voice and framing
- Goal: record their authentic perspective
""",

    "coaching": """
INTERVIEW APPROACH: Coaching
- You are helping the guest think through something for themselves
- Reflect back what you hear; ask what *they* think
- Don't provide answers or opinions; facilitate their insight
- Use Socratic questioning to help them discover their own views
- Goal: help the guest arrive at their own understanding
""",
}
```

### Resolution Logic

```python
def get_effective_config(interview: Interview, template: InterviewTemplate | None):
    """Resolve content and style, interview overrides template."""
    return {
        "questions": interview.questions or (template.questions if template else None),
        "research_summary": interview.research_summary or (template.research_summary if template else None),
        "research_links": interview.research_links or (template.research_links if template else None),
        "angle": interview.angle or (template.angle if template else InterviewAngle.EXPLORATORY),
        "angle_secondary": interview.angle_secondary or (template.angle_secondary if template else None),
        "angle_custom": interview.angle_custom or (template.angle_custom if template else None),
    }
```

### Prompt Building

```python
def build_interview_prompt(interview: Interview, template: InterviewTemplate | None):
    config = get_effective_config(interview, template)

    prompt = BASE_PROMPT

    # Add style section
    angle = config["angle"]
    if angle == InterviewAngle.CUSTOM:
        prompt += f"\n{config['angle_custom']}"
    else:
        prompt += ANGLE_PROMPTS[angle.value]
        if config["angle_secondary"] and config["angle_secondary"] != InterviewAngle.CUSTOM:
            prompt += f"\nSECONDARY APPROACH:\nAlso incorporate elements of the {config['angle_secondary'].value} style:\n{ANGLE_PROMPTS[config['angle_secondary'].value]}"

    # Add content section
    if config["research_summary"]:
        prompt += f"\nRESEARCH MATERIALS:\n{config['research_summary']}"
    if config["questions"]:
        prompt += f"\nPREPARED QUESTIONS:\n{format_questions(config['questions'])}"

    # Add person context
    if interview.context_notes:
        prompt += f"\nABOUT THIS INTERVIEWEE ({interview.name}):\n{interview.context_notes}"

    return prompt
```

---

## UI Flows

### Interview Template Creation/Edit

```
┌─────────────────────────────────────────┐
│ New Interview Template                  │
├─────────────────────────────────────────┤
│ TEMPLATE INFO                           │
│ ├─ Name*: [Customer Discovery      ]    │
│ └─ Description: [Open-ended research    │
│                  interviews...]         │
├─────────────────────────────────────────┤
│ CONTENT                                 │
│ ├─ Questions: [textarea, one per line]  │
│ ├─ Research links: [URLs, one per line] │
│ ├─ Upload files: [file picker]          │
│ └─ Default duration: [30] min           │
├─────────────────────────────────────────┤
│ STYLE                                   │
│ ├─ Approach*: [Exploratory        ▼]    │
│ │   ○ Exploratory - learning from guest │
│ │   ○ Interrogative - testing claims    │
│ │   ○ Imaginative - building ideas      │
│ │   ○ Documentary - capturing story     │
│ │   ○ Coaching - facilitating insight   │
│ │   ○ Custom - define your own          │
│ │                                       │
│ └─ Blend with: [None              ▼]    │
│     (optional secondary approach)       │
├─────────────────────────────────────────┤
│           [Save Template]               │
└─────────────────────────────────────────┘
```

### Interview Creation (updated)

```
┌─────────────────────────────────────────┐
│ Add Interview                           │
├─────────────────────────────────────────┤
│ INTERVIEWEE                             │
│ ├─ Name*: [Steve Johnson           ]    │
│ └─ Email: [steve@example.com       ]    │
├─────────────────────────────────────────┤
│ INTERVIEW TYPE                          │
│ │                                       │
│ │  ○ Customer Discovery                 │
│ │    Exploratory · 30 min               │
│ │                                       │
│ │  ○ Expert Challenge                   │
│ │    Interrogative · 45 min             │
│ │                                       │
│ │  ○ Story Capture                      │
│ │    Documentary · 60 min               │
│ │  ──────────────────                   │
│ │  ● Other                              │
│ │                                       │
│ │  ┌─ CONTENT ────────────────────────┐ │
│ │  │ Questions: [textarea]            │ │
│ │  │ Research links: [urls]           │ │
│ │  │ Upload files: [file picker]      │ │
│ │  │ Duration: [30] min               │ │
│ │  └──────────────────────────────────┘ │
│ │                                       │
│ │  ┌─ STYLE ──────────────────────────┐ │
│ │  │ Approach*: [Exploratory      ▼]  │ │
│ │  │ Blend with: [None            ▼]  │ │
│ │  └──────────────────────────────────┘ │
│ │                                       │
│ │  ☐ Save as template for reuse        │
│ │    Template name: [              ]    │
│ │                                       │
├─────────────────────────────────────────┤
│ BACKGROUND ON THIS PERSON (optional)    │
│ ├─ Notes: [context about interviewee]   │
│ ├─ Links: [LinkedIn, company page...]   │
│ └─ Files: [bio, past notes...]          │
├─────────────────────────────────────────┤
│     [Create Interview]                  │
└─────────────────────────────────────────┘
```

---

## Implementation Tasks

### 1. Database Migration - Add Angle Fields

**Files:**
- Create: `migrations/versions/XXXX_add_interview_angles.py`
- Modify: `src/boswell/server/models.py`

**Changes:**
- Add `InterviewAngle` enum type to database
- Add to InterviewTemplate: `angle`, `angle_secondary`, `angle_custom`, `questions`, `research_summary`, `research_links`
- Add to Interview: `template_id`, `questions`, `research_summary`, `research_links`, `angle`, `angle_secondary`, `angle_custom`
- Remove `template_id` from Project

### 2. Update Models

**Files:**
- Modify: `src/boswell/server/models.py`

**Changes:**
- Add `InterviewAngle` enum class
- Update `InterviewTemplate` with new fields
- Update `Interview` with new fields
- Update `Project` to remove `template_id`
- Update relationships

### 3. Add Angle Prompts

**Files:**
- Modify: `src/boswell/voice/prompts.py`

**Changes:**
- Add `ANGLE_PROMPTS` dictionary
- Add `get_effective_config()` function
- Update `build_system_prompt()` to incorporate angle

### 4. Update Interview Template UI

**Files:**
- Modify: `src/boswell/server/templates/admin/template_form.html`
- Modify: `src/boswell/server/routes/admin.py`

**Changes:**
- Add content fields (questions, research links, file upload)
- Add style fields (angle dropdown, secondary dropdown)
- Handle custom angle textarea
- Update form submission handler

### 5. Update Interview Creation UI

**Files:**
- Modify: `src/boswell/server/templates/admin/interview_new.html`
- Modify: `src/boswell/server/routes/admin.py`

**Changes:**
- Replace simple template dropdown with radio button list
- Add "Other" option with expandable content + style sections
- Add "Save as template" checkbox with name field
- Update form submission to handle both template and custom paths

### 6. Update Voice Pipeline

**Files:**
- Modify: `src/boswell/server/worker.py`
- Modify: `src/boswell/voice/prompts.py`

**Changes:**
- Fetch interview's template (if set)
- Call `get_effective_config()` to resolve content + style
- Pass resolved config to `build_system_prompt()`

### 7. Update Project Creation (remove template)

**Files:**
- Modify: `src/boswell/server/templates/admin/project_new.html`
- Modify: `src/boswell/server/routes/admin.py`

**Changes:**
- Remove template_id dropdown from project creation
- Projects are now just containers; template selection happens at interview level

### 8. Test and Deploy

**Manual testing:**
1. Create interview template with content + style
2. Create interview using template
3. Create interview using "Other" with custom content + style
4. Create interview using "Other" and save as new template
5. Verify Boswell uses correct angle in voice session
6. Test angle blending (primary + secondary)

---

## Summary

| Component | Change |
|-----------|--------|
| Enum | New `InterviewAngle` with 5 presets + custom |
| InterviewTemplate | Add content fields + angle fields |
| Interview | Add template_id + content/angle overrides |
| Project | Remove template_id |
| Prompts | Add `ANGLE_PROMPTS`, update builder |
| Template UI | Add content + style sections |
| Interview UI | Radio list of templates + "Other" option |
| Worker | Resolve config from interview + template |
