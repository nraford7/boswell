"""Output processing for Boswell.

Handles generation of transcript.md and insights.md from raw interview data.
Uses Claude to clean transcripts and extract insights.
"""

from datetime import datetime
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from boswell.config import load_config
from boswell.interview import Interview, load_interview, save_interview


class TranscriptOutput(BaseModel):
    """Structured transcript output."""

    interview_id: str
    guest_name: str | None
    date: str
    duration_minutes: int
    topic: str
    content: str  # Markdown formatted transcript


class InsightsOutput(BaseModel):
    """Structured insights output."""

    interview_id: str
    themes: list[dict] = Field(default_factory=list)
    key_quotes: list[dict] = Field(default_factory=list)
    content: str  # Markdown formatted insights


# Prompt for cleaning transcripts
CLEAN_TRANSCRIPT_PROMPT = """\
You are processing a raw interview transcript into clean, readable markdown.

Interview topic: {topic}
Guest name: {guest_name}
Date: {date}

Raw transcript (speaker, text, timestamp entries):
{raw_transcript}

Convert this into a clean, well-formatted interview transcript following these rules:
1. Use **Boswell:** and **{guest_label}:** as speaker labels
2. Clean up filler words (um, uh, like) where they don't add meaning
3. Fix obvious transcription errors if context makes the intent clear
4. Keep the natural conversational flow
5. Do not add content that wasn't in the original
6. Do not summarize - include the full conversation

Output ONLY the formatted dialogue, starting directly with the first speaker.
Do not include frontmatter or headers - just the dialogue.
"""

# Prompt for extracting insights
EXTRACT_INSIGHTS_PROMPT = """\
You are analyzing an interview transcript to extract key insights and themes.

Interview topic: {topic}

Full transcript:
{transcript}

Extract the following and format as markdown:

1. **Key Themes** (3-5 major themes discussed)
   - For each theme: a brief description and why it matters

2. **Notable Quotes** (5-8 compelling quotes)
   - Include the quote in blockquote format
   - Add approximate timestamp if available
   - Brief context for why this quote is significant

3. **Surprising Insights** (2-3 unexpected or particularly interesting points)

4. **Summary** (2-3 paragraph overview of the interview)

Format your response as clean markdown with clear headers.
Start with "# Key Insights" as the main header.
"""


def clean_transcript(raw_transcript: list[dict], interview: Interview) -> str:
    """Convert raw transcript to clean markdown with speaker labels.

    Args:
        raw_transcript: List of {{speaker, text, timestamp}} entries
        interview: Interview model with metadata

    Returns:
        Markdown with YAML frontmatter and formatted dialogue
    """
    # Calculate duration from transcript timestamps
    duration_minutes = _calculate_duration(raw_transcript)

    # Format date
    date_str = interview.created_at.strftime("%Y-%m-%d")

    # Guest label
    guest_label = interview.guest_name if interview.guest_name else "Guest"

    # Format raw transcript for the prompt
    formatted_raw = _format_raw_transcript(raw_transcript)

    # Call Claude to clean the transcript
    config = load_config()
    if config is None or not config.claude_api_key:
        raise RuntimeError("Claude API key not configured. Run 'boswell init' first.")

    client = anthropic.Anthropic(api_key=config.claude_api_key)

    prompt = CLEAN_TRANSCRIPT_PROMPT.format(
        topic=interview.topic,
        guest_name=guest_label,
        date=date_str,
        raw_transcript=formatted_raw,
        guest_label=guest_label,
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    cleaned_dialogue = message.content[0].text

    # Build the full markdown with frontmatter
    frontmatter = f"""---
interview_id: {interview.id}
guest: {guest_label}
date: {date_str}
duration: {duration_minutes}min
topic: {interview.topic}
---

# Interview Transcript

"""

    return frontmatter + cleaned_dialogue


def extract_insights(transcript: str, topic: str) -> str:
    """Use Claude to extract themes, key quotes, and insights.

    Args:
        transcript: The cleaned transcript markdown
        topic: Interview topic for context

    Returns:
        Structured markdown with themes and quotes
    """
    config = load_config()
    if config is None or not config.claude_api_key:
        raise RuntimeError("Claude API key not configured. Run 'boswell init' first.")

    client = anthropic.Anthropic(api_key=config.claude_api_key)

    prompt = EXTRACT_INSIGHTS_PROMPT.format(
        topic=topic,
        transcript=transcript,
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def export_interview(
    interview_id: str,
    output_dir: Path,
    raw_transcript: list[dict] | None = None,
) -> tuple[Path, Path]:
    """Export transcript.md and insights.md to output directory.

    Args:
        interview_id: The interview ID to export
        output_dir: Directory to write output files
        raw_transcript: Optional raw transcript data. If not provided,
                       will use the interview's stored transcript data.

    Returns:
        Tuple of (transcript_path, insights_path)

    Raises:
        ValueError: If interview not found
        RuntimeError: If no transcript data available
    """
    # Load the interview
    interview = load_interview(interview_id)
    if interview is None:
        raise ValueError(f"Interview not found: {interview_id}")

    # Get transcript data
    if raw_transcript is None:
        # Try to load from stored conversation state
        # For now, we'll require it to be passed in
        raise RuntimeError(
            "No transcript data provided. "
            "Pass raw_transcript or ensure interview has transcript data."
        )

    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate clean transcript
    transcript_content = clean_transcript(raw_transcript, interview)

    # Write transcript.md
    transcript_path = output_dir / "transcript.md"
    transcript_path.write_text(transcript_content)

    # Extract insights
    insights_content = extract_insights(transcript_content, interview.topic)

    # Write insights.md
    insights_path = output_dir / "insights.md"
    insights_path.write_text(insights_content)

    # Update interview with output directory
    interview.output_dir = str(output_dir)
    save_interview(interview)

    return transcript_path, insights_path


def generate_output_path(
    interview_id: str,
    guest_name: str | None,
    date: str,
) -> Path:
    """Generate the output directory path for an interview.

    Format: outputs/YYYY-MM-DD-guest-name/

    Args:
        interview_id: Interview ID
        guest_name: Guest name (optional)
        date: Interview date (YYYY-MM-DD format)

    Returns:
        Path to output directory
    """
    # Sanitize guest name for filesystem
    if guest_name:
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "-"
            for c in guest_name.lower()
        )
        # Remove consecutive dashes
        while "--" in safe_name:
            safe_name = safe_name.replace("--", "-")
        safe_name = safe_name.strip("-")
    else:
        safe_name = interview_id

    dir_name = f"{date}-{safe_name}"
    return Path("outputs") / dir_name


def _calculate_duration(raw_transcript: list[dict]) -> int:
    """Calculate interview duration from transcript timestamps.

    Args:
        raw_transcript: List of transcript entries with timestamps

    Returns:
        Duration in minutes (rounded up)
    """
    if not raw_transcript:
        return 0

    # Try to parse first and last timestamps
    try:
        first_ts = raw_transcript[0].get("timestamp", "")
        last_ts = raw_transcript[-1].get("timestamp", "")

        if first_ts and last_ts:
            # Parse ISO format timestamps
            first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            duration_seconds = (last_dt - first_dt).total_seconds()
            # Round up to nearest minute
            return max(1, int(duration_seconds / 60 + 0.5))
    except (ValueError, TypeError, KeyError):
        pass

    # Fallback: estimate based on transcript length
    # Rough estimate: ~150 words per minute of speech
    total_words = sum(len(entry.get("text", "").split()) for entry in raw_transcript)
    return max(1, total_words // 150)


def _format_raw_transcript(raw_transcript: list[dict]) -> str:
    """Format raw transcript entries for the cleaning prompt.

    Args:
        raw_transcript: List of {speaker, text, timestamp} entries

    Returns:
        Formatted string representation
    """
    lines = []
    for entry in raw_transcript:
        speaker = entry.get("speaker", "unknown")
        text = entry.get("text", "")
        timestamp = entry.get("timestamp", "")

        # Format timestamp if present
        ts_str = ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts_str = f" [{dt.strftime('%H:%M:%S')}]"
            except (ValueError, TypeError):
                ts_str = f" [{timestamp}]"

        lines.append(f"[{speaker}]{ts_str}: {text}")

    return "\n".join(lines)
