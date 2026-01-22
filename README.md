# Boswell: AI Research Interviewer

An open-source AI interviewer that joins Zoom/Meet calls, conducts research-informed interviews autonomously, and outputs structured transcripts and insights.

## Overview

Boswell is designed for researchers and journalists who need to conduct substantive interviews at scale without losing the human touch. You provide a topic and research materials, Boswell generates a meeting link. Your guest joins, and the AI conducts a dynamic, research-informed interview.

## Quick Start

### Prerequisites

- Python 3.11+
- API keys for: Claude, ElevenLabs, Deepgram, MeetingBaaS

### Installation

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
```

### Docker Installation

```bash
# Clone and set up
git clone https://github.com/yourname/boswell
cd boswell
cp .env.example .env
# Edit .env with your API keys

# Build and run
docker-compose up -d
docker-compose run boswell init
```

### Usage

```bash
# Initialize configuration (one-time setup)
boswell init

# Create a new interview
boswell create --topic "AI safety research" --docs ./research/

# Check interview status
boswell status int_7x8f2k

# Export outputs when complete
boswell export int_7x8f2k --output ./interviews/

# List all interviews
boswell list
```

## Documentation

See [docs/plans/2025-01-22-boswell-design.md](docs/plans/2025-01-22-boswell-design.md) for the full design document.

## Tech Stack

- **Voice Framework**: Pipecat
- **Meeting Integration**: speaking-meeting-bot / MeetingBaaS
- **Text-to-Speech**: ElevenLabs
- **Speech-to-Text**: Deepgram
- **LLM**: Claude API
- **CLI**: Typer

## License

MIT
