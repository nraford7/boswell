# Persistent Named Guest Links - Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

## Overview

Allow named guests to reuse their magic link after completing an interview, with options to resume, add detail, or start fresh.

**Scope:** Named guest links only (not generic/public links)

## User Flow

1. Guest clicks their magic link (`/i/{magic_token}`)
2. System creates a new Daily room (regardless of previous interview status)
3. Guest joins the room
4. Bot detects this is a returning guest with a completed interview
5. Bot greets them: *"Welcome back, [Name]! I see we spoke before. Would you like to pick up where we left off, add detail to your previous answers, or start completely fresh?"*
6. Guest responds verbally
7. Bot proceeds based on their choice:
   - **Resume** → continues conversation with full prior context
   - **Add Detail** → offers to review/refine answers conversationally
   - **Fresh Start** → bot confirms, then proceeds as new interview
8. Interview completes, single transcript saved (appended, amended, or fresh)

## Three Modes

### Resume
- Bot has full previous conversation context
- Continues where they left off
- New transcript entries appended to existing transcript
- Single transcript remains (old + new combined)

### Add Detail
- Bot has previous transcript for reference
- Asks conversationally: "Would you like to add anything new, refine a specific answer, or run through the questions to jog your memory?"
- Adapts to guest's needs
- Creates amended transcript (old + refinements merged)
- Single transcript remains (amended version)

### Fresh Start
- Bot confirms before proceeding: "Just to confirm - you'd like to start completely fresh? This will replace your previous answers. Is that okay?"
- Only after verbal confirmation does system delete old transcript
- Starts completely new interview with no prior context
- Single transcript remains (new one)

## Database Changes

### Status Cycling
Allow `completed` interviews to transition back to `started`:
```
invited → started → completed → started → completed (repeatable)
```

### New Field
Add to Interview/Guest model:
```python
session_count: int = 1  # Incremented each time they start a new session
```

### Existing Fields (No Change)
- `magic_token` - remains permanent and unique
- `Transcript.entries` - JSONB array of transcript entries
- `Transcript.conversation_context` - JSONB array of conversation messages

### Relationships (No Change)
- One `Transcript` record per guest (updated, not multiplied)
- One `Analysis` record per guest (regenerated after each session)

## Route Changes

### Landing Page (`GET /i/{magic_token}`)
- Currently shows "completed" message for finished interviews
- Change to: show "Start or Resume Interview" button for named guests with completed interviews
- New guests still see "Start Interview"

### Start Interview (`POST /i/{magic_token}/start`)
- Currently rejects if `status == completed`
- Change to: allow re-starting completed interviews
- Set flag `is_returning = True` if previous transcript exists
- Increment `session_count`

### Room Page (`GET /i/{magic_token}/room`)
- No change needed

## Voice Pipeline Changes

### Data Passed to Pipeline
When starting a returning guest's session:
```python
{
    "is_returning": True,
    "previous_transcript": [...],  # From Transcript.entries
    "previous_context": [...],     # From Transcript.conversation_context
}
```

### System Prompt Injection
When `is_returning = True`, add to system prompt:
```
This guest has completed a previous interview. When they join, greet them warmly
and ask what they'd like to do:

1. RESUME - Pick up where you left off (they may have been cut off or want to add more)
2. ADD DETAIL - Review and refine previous answers (offer to jog their memory or let them specify)
3. FRESH START - Start completely over (confirm before proceeding, as this erases previous answers)

Listen for their intent and proceed accordingly. You can be flexible - if they ask to
reference previous answers later, accommodate them (unless they chose Fresh Start and
confirmed deletion).

Their previous conversation:
<previous_transcript>
{transcript_entries}
</previous_transcript>
```

### Mode Signaling
Bot sends app message when guest confirms choice:
```json
{"type": "interview_mode", "mode": "resume" | "add_detail" | "fresh_start"}
```
This is stored on the Interview record for the worker to read.

## Worker Changes

### Transcript Handling by Mode

| Mode | Action |
|------|--------|
| Resume | Append new entries to existing transcript |
| Add Detail | Replace transcript with combined conversation |
| Fresh Start | Delete old transcript/analysis, create new |

### Analysis Regeneration
After any mode completes, regenerate analysis on the final transcript.

## Edge Cases

### Guest disconnects before choosing mode
- Interview stays in `started` status
- On rejoin, bot asks the same question again
- Previous transcript untouched until mode confirmed

### Guest never confirms Fresh Start
- If they say "fresh start" but disconnect before confirming, previous transcript preserved
- Confirmation required before any deletion

### Guest changes mind mid-interview
- Resume/Add Detail: Can reference previous answers anytime
- Fresh Start: Once confirmed and deleted, previous answers gone

### Multiple return visits
- Each return follows same flow
- Transcript keeps growing (Resume), gets amended (Add Detail), or replaced (Fresh Start)
- `session_count` increments for tracking

## Files to Modify

| File | Changes |
|------|---------|
| `models.py` | Add `session_count` field, migration |
| `routes/guest.py` | Allow completed interviews to restart, pass returning flag |
| `pipeline.py` | Accept and use returning guest context |
| `worker.py` | Handle transcript append/amend/replace based on mode |
| `templates/guest/landing.html` | "Start or Resume Interview" button text |
| System prompt construction | Add returning guest instructions |

## Summary Table

| Aspect | Decision |
|--------|----------|
| Scope | Named guests only |
| Choice UI | Bot asks verbally in room |
| Options | Resume, Add Detail, Fresh Start |
| Transcript handling | One transcript per guest (append/amend/replace) |
| Mode signaling | App message from bot → stored on Interview |
| Fresh Start safety | Verbal confirmation required before deletion |
| Status cycling | `completed → started` allowed for returns |
| New field | `session_count` on Interview |
