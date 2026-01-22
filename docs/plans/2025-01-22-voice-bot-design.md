# Boswell Voice Bot Design

## Overview

Replace MeetingBaaS with Daily.co + Pipecat to create a voice bot that conducts interviews autonomously.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Local Mac (Pipecat server)                    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Pipecat Pipeline                       │   │
│  │                                                           │   │
│  │   Daily.co  ──▶  Deepgram  ──▶  Claude  ──▶  ElevenLabs  │   │
│  │   (audio in)     (STT)        (brain)       (TTS)        │   │
│  │                                                           │   │
│  │   ElevenLabs ──▶ Daily.co                                │   │
│  │   (audio out)    (to guest)                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────┐                                               │
│  │   Boswell    │  CLI creates interview, starts bot,           │
│  │     CLI      │  generates questions, exports results         │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ WebRTC
                    ┌───────────────────┐
                    │     Daily.co      │
                    │       Room        │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Guest browser   │
                    │  (clicks link)    │
                    └───────────────────┘
```

## Low-Latency Response Strategy

Target: < 500ms response time (vs 2-3 seconds without optimization)

**While guest is speaking:**
1. Deepgram streams partial transcript in real-time
2. Claude receives partial transcript, generates candidate responses
3. ElevenLabs pre-synthesizes top candidate audio

**When guest stops speaking:**
1. Final transcript arrives
2. Claude picks best response (or generates fresh if unexpected)
3. Audio already synthesized → plays immediately

## Conversation Logic

Claude manages the interview via prompting (no hardcoded state machine):

**Context window contains:**
- System prompt: NPR-style interviewer persona
- Interview topic + research summary
- Generated questions (as guide, not script)
- Full transcript so far
- Time remaining, questions covered

**Each turn, Claude decides:**
1. Follow interesting thread? → Ask follow-up
2. Connects to prepared question? → Bridge naturally
3. Time to check in? (~5 exchanges) → Ask about time/energy
4. Otherwise → Next prepared question

## CLI Workflow

```bash
# 1. CREATE INTERVIEW
$ boswell create --topic "AI Safety" --docs paper.pdf
  ✓ Research processed
  ✓ 12 questions generated
  Interview ID: int_abc123

# 2. START INTERVIEW (new command)
$ boswell start int_abc123
  ✓ Daily.co room created
  ✓ Pipecat bot joined

  Send this link to your guest:
  https://daily.co/boswell/int_abc123

  Bot is waiting in room...
  Press Ctrl+C to end interview

  [Live transcript streams here]

# 3. EXPORT
$ boswell export int_abc123 --output ./interview/
  ✓ transcript.md saved
  ✓ insights.md saved
```

## Tech Stack

**Services (API keys):**
- Daily.co - Video rooms, WebRTC (free tier: 10k min/mo)
- Deepgram - Speech-to-text
- ElevenLabs - Text-to-speech
- Claude - Conversation brain

**Python packages:**
- pipecat-ai - Voice pipeline framework
- pipecat-ai[daily] - Daily.co transport
- pipecat-ai[deepgram] - Deepgram STT
- pipecat-ai[elevenlabs] - ElevenLabs TTS
- pipecat-ai[anthropic] - Claude integration

## Files to Add

```
boswell/
├── src/boswell/
│   ├── voice/
│   │   ├── __init__.py
│   │   ├── pipeline.py    # Pipecat pipeline setup
│   │   ├── bot.py         # Interview bot logic
│   │   └── prompts.py     # System prompts for Claude
│   └── cli.py             # Add 'start' command
└── pyproject.toml         # Add pipecat dependencies
```

## What We Keep

- Config management (add Daily.co API key)
- Interview model & persistence
- Research ingestion & question generation
- Output processing (transcript → insights)

## What We Replace

- MeetingBaaS integration → Daily.co + Pipecat

## Cost Estimate (350 interviews)

- Daily.co: ~$44 (21,000 min - 10,000 free = 11,000 × $0.004)
- Deepgram: Usage-based (~$0.0043/min)
- ElevenLabs: Usage-based (depends on plan)
- Claude: Usage-based (input/output tokens)
