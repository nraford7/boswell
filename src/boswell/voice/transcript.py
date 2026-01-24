"""Transcript capture for Boswell voice interviews."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    TextFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


@dataclass
class TranscriptEntry:
    """A single entry in the transcript."""

    timestamp: str
    speaker: str  # "guest" or "boswell"
    text: str
    struck: bool = False  # True if guest requested this be removed

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "timestamp": self.timestamp,
            "speaker": self.speaker,
            "text": self.text,
        }
        if self.struck:
            result["struck"] = True
        return result


class TranscriptCollector(FrameProcessor):
    """Collects transcript entries from the Pipecat pipeline.

    Captures:
    - TranscriptionFrame: Guest speech (from Deepgram STT)
    - UserStoppedSpeakingFrame: Flushes accumulated guest speech as one entry

    Guest speech is aggregated until they stop speaking, then flushed as a
    complete utterance rather than fragmented chunks.
    """

    def __init__(self, guest_name: str = "Guest", **kwargs):
        super().__init__(**kwargs)
        self.guest_name = guest_name
        self.entries: list[TranscriptEntry] = []
        self._current_guest_text: str = ""
        self._guest_turn_start: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and capture transcript entries."""
        await super().process_frame(frame, direction)

        # Accumulate guest speech from STT
        if isinstance(frame, TranscriptionFrame):
            if frame.text and frame.text.strip():
                # Record timestamp of first speech in this turn
                if not self._guest_turn_start:
                    self._guest_turn_start = datetime.now(timezone.utc).isoformat()
                # Accumulate text (add space between chunks)
                if self._current_guest_text:
                    self._current_guest_text += " " + frame.text.strip()
                else:
                    self._current_guest_text = frame.text.strip()

        # Flush guest speech when they stop speaking
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._flush_guest_text()

        # Push frame downstream
        await self.push_frame(frame, direction)

    def _flush_guest_text(self) -> None:
        """Flush accumulated guest text as a single transcript entry."""
        if self._current_guest_text.strip():
            timestamp = self._guest_turn_start or datetime.now(timezone.utc).isoformat()
            self.entries.append(
                TranscriptEntry(
                    timestamp=timestamp,
                    speaker=self.guest_name,
                    text=self._current_guest_text.strip(),
                )
            )
            self._current_guest_text = ""
            self._guest_turn_start = None

    def to_json(self) -> str:
        """Export transcript as JSON string."""
        return json.dumps(
            [entry.to_dict() for entry in self.entries],
            indent=2,
        )

    def save(self, path: Path) -> None:
        """Save transcript to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())

    def get_entries(self) -> list[dict[str, Any]]:
        """Get transcript entries as list of dicts."""
        return [entry.to_dict() for entry in self.entries]

    def get_entries_excluding_struck(self) -> list[dict[str, Any]]:
        """Get transcript entries excluding struck content."""
        return [entry.to_dict() for entry in self.entries if not entry.struck]

    def strike_last_guest_entry(self) -> bool:
        """Mark the last guest entry as struck from the record.

        Returns:
            True if an entry was struck, False if no guest entry found.
        """
        # Find the last guest entry and mark it as struck
        for entry in reversed(self.entries):
            if entry.speaker == "guest" and not entry.struck:
                entry.struck = True
                return True
        return False


class BotResponseCollector(FrameProcessor):
    """Collects complete bot responses by detecting response boundaries.

    This processor sits after the LLM and captures full responses.
    Flushes when LLMFullResponseEndFrame is received, ensuring each
    Boswell response is captured as a complete entry.
    """

    def __init__(self, transcript_collector: TranscriptCollector, **kwargs):
        super().__init__(**kwargs)
        self._transcript = transcript_collector
        self._current_response = ""
        self._response_start: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and capture complete bot responses."""
        await super().process_frame(frame, direction)

        # Accumulate text frames
        if isinstance(frame, TextFrame) and frame.text:
            if not self._response_start:
                self._response_start = datetime.now(timezone.utc).isoformat()
            self._current_response += frame.text

        # Flush when LLM response is complete
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._flush()

        # Push frame downstream
        await self.push_frame(frame, direction)

    def _flush(self) -> None:
        """Flush the current response to the transcript."""
        if self._current_response.strip():
            timestamp = self._response_start or datetime.now(timezone.utc).isoformat()
            self._transcript.entries.append(
                TranscriptEntry(
                    timestamp=timestamp,
                    speaker="boswell",
                    text=self._current_response.strip(),
                )
            )
            self._current_response = ""
            self._response_start = None

    def flush(self) -> None:
        """Public flush for end-of-interview cleanup."""
        self._flush()
