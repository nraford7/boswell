"""Transcript capture for Boswell voice interviews."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    Frame,
    TextFrame,
    TranscriptionFrame,
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
    - TextFrame: Bot responses (from Claude via TTS)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.entries: list[TranscriptEntry] = []
        self._current_bot_text: str = ""
        self._last_guest_text: str = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and capture transcript entries."""
        await super().process_frame(frame, direction)

        timestamp = datetime.now(timezone.utc).isoformat()

        # Capture guest speech from STT
        if isinstance(frame, TranscriptionFrame):
            # Only capture final transcriptions, not interim
            if frame.text and frame.text.strip():
                # Avoid duplicate entries
                if frame.text != self._last_guest_text:
                    self._last_guest_text = frame.text
                    self.entries.append(
                        TranscriptEntry(
                            timestamp=timestamp,
                            speaker="guest",
                            text=frame.text.strip(),
                        )
                    )

        # Capture bot speech going to TTS
        elif isinstance(frame, TextFrame):
            # TextFrames contain chunks of bot response
            if frame.text:
                self._current_bot_text += frame.text

        # Push frame downstream
        await self.push_frame(frame, direction)

    def flush_bot_text(self) -> None:
        """Flush accumulated bot text as a transcript entry."""
        if self._current_bot_text.strip():
            timestamp = datetime.now(timezone.utc).isoformat()
            self.entries.append(
                TranscriptEntry(
                    timestamp=timestamp,
                    speaker="boswell",
                    text=self._current_bot_text.strip(),
                )
            )
            self._current_bot_text = ""

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

    This processor sits after the LLM and captures full responses
    rather than individual text chunks.
    """

    def __init__(self, transcript_collector: TranscriptCollector, **kwargs):
        super().__init__(**kwargs)
        self._transcript = transcript_collector
        self._current_response = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and capture complete bot responses."""
        await super().process_frame(frame, direction)

        # Accumulate text frames
        if isinstance(frame, TextFrame) and frame.text:
            self._current_response += frame.text

        # Push frame downstream
        await self.push_frame(frame, direction)

    def flush(self) -> None:
        """Flush the current response to the transcript."""
        if self._current_response.strip():
            timestamp = datetime.now(timezone.utc).isoformat()
            self._transcript.entries.append(
                TranscriptEntry(
                    timestamp=timestamp,
                    speaker="boswell",
                    text=self._current_response.strip(),
                )
            )
            self._current_response = ""
