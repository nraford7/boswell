"""Output processing for Boswell.

Handles generation of transcript.md and insights.md from raw interview data.
Two Claude calls: clean transcript, extract insights.
"""

from pathlib import Path

from pydantic import BaseModel, Field


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


def clean_transcript(raw_transcript: list[dict], metadata: dict) -> TranscriptOutput:
    """Process raw Deepgram transcript into clean markdown.

    Args:
        raw_transcript: Raw transcript data from Deepgram
        metadata: Interview metadata (id, guest, date, topic, etc.)

    Returns:
        Cleaned and formatted TranscriptOutput
    """
    # TODO: Implement transcript cleanup via Claude
    raise NotImplementedError("Transcript cleanup not yet implemented")


def extract_insights(transcript: TranscriptOutput) -> InsightsOutput:
    """Extract key themes and insights from transcript.

    Uses Claude to identify:
    - Major themes discussed
    - Key quotes with timestamps
    - Surprising or notable points

    Args:
        transcript: Cleaned transcript

    Returns:
        Extracted InsightsOutput
    """
    # TODO: Implement insight extraction via Claude
    raise NotImplementedError("Insight extraction not yet implemented")


def write_outputs(
    transcript: TranscriptOutput,
    insights: InsightsOutput,
    output_dir: Path,
    audio_path: Path | None = None,
) -> None:
    """Write all interview outputs to disk.

    Creates:
    - transcript.md
    - insights.md
    - raw/audio.wav (if provided)

    Args:
        transcript: Cleaned transcript
        insights: Extracted insights
        output_dir: Directory to write outputs
        audio_path: Optional path to raw audio file
    """
    # TODO: Implement output file writing
    raise NotImplementedError("Output writing not yet implemented")


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
        date: Interview date

    Returns:
        Path to output directory
    """
    # TODO: Implement path generation
    raise NotImplementedError("Output path generation not yet implemented")
