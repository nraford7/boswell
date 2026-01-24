"""Transcript capture for Boswell voice interviews."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Filler patterns that should be merged with the next response
FILLER_PATTERNS = re.compile(
    r"^(mm-hmm|mm hmm|mmhmm|mm|mhm|uh-huh|uh huh|uhuh|"
    r"i see|got it|right|yes|okay|ok|interesting|absolutely|"
    r"sure|exactly|indeed|great|good|wonderful|perfect)\.?$",
    re.IGNORECASE
)


def is_filler(text: str) -> bool:
    """Check if text is a short filler response."""
    text = text.strip()
    # Short responses that match filler patterns
    if len(text) < 25 and FILLER_PATTERNS.match(text):
        return True
    return False


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

    Uses turn-based detection: flushes guest speech when Boswell starts
    responding, ensuring natural conversation flow in the transcript.
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

    def flush_on_bot_response(self) -> None:
        """Called by BotResponseCollector when Boswell starts speaking."""
        self._flush_guest_text()

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
        """Get transcript entries as list of dicts, post-processed."""
        return self._post_process_entries()

    def get_entries_excluding_struck(self) -> list[dict[str, Any]]:
        """Get transcript entries excluding struck content."""
        entries = self._post_process_entries()
        return [e for e in entries if not e.get("struck")]

    def _post_process_entries(self) -> list[dict[str, Any]]:
        """Post-process entries: sort by timestamp and merge consecutive same-speaker."""
        if not self.entries:
            return []

        # Convert to dicts and sort by timestamp
        sorted_entries = sorted(
            [e.to_dict() for e in self.entries],
            key=lambda x: x["timestamp"]
        )

        # Merge consecutive same-speaker entries
        merged = []
        for entry in sorted_entries:
            if not merged:
                merged.append(entry)
                continue

            prev = merged[-1]
            # Same speaker? Merge the text
            if prev["speaker"] == entry["speaker"]:
                # Add space or newline between merged texts
                prev["text"] = prev["text"].rstrip() + " " + entry["text"].lstrip()
            else:
                merged.append(entry)

        # Clean up merged Boswell entries - remove duplicate fillers
        for entry in merged:
            if entry["speaker"] == "boswell":
                entry["text"] = self._clean_boswell_text(entry["text"])

        return merged

    def _clean_boswell_text(self, text: str) -> str:
        """Clean up Boswell text by removing repeated fillers."""
        # Split on common filler boundaries and rejoin unique parts
        # Pattern: "Got it.Got it. So what..." -> "Got it. So what..."
        parts = re.split(r'(?<=[.!?])\s*(?=[A-Z])', text)
        seen_fillers = set()
        cleaned = []

        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Check if it's a standalone filler we've already seen
            if is_filler(part):
                filler_key = part.lower().rstrip('.')
                if filler_key in seen_fillers:
                    continue  # Skip duplicate filler
                seen_fillers.add(filler_key)
            cleaned.append(part)

        return " ".join(cleaned)

    def strike_last_guest_entry(self) -> bool:
        """Mark the last guest entry as struck from the record.

        Returns:
            True if an entry was struck, False if no guest entry found.
        """
        # Find the last guest entry and mark it as struck
        for entry in reversed(self.entries):
            if entry.speaker == self.guest_name and not entry.struck:
                entry.struck = True
                return True
        return False


class BotResponseCollector(FrameProcessor):
    """Collects complete bot responses by detecting response boundaries.

    Flushes guest speech when Boswell starts speaking (turn-based detection).
    Filters out very short filler responses and merges them with the next response.
    """

    def __init__(self, transcript_collector: TranscriptCollector, **kwargs):
        super().__init__(**kwargs)
        self._transcript = transcript_collector
        self._current_response = ""
        self._response_start: str | None = None
        self._pending_filler: str = ""
        self._pending_filler_timestamp: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and capture complete bot responses."""
        await super().process_frame(frame, direction)

        # When Boswell starts a new response, flush any pending guest speech
        if isinstance(frame, LLMFullResponseStartFrame):
            self._transcript.flush_on_bot_response()

        # Accumulate text frames
        elif isinstance(frame, TextFrame) and frame.text:
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
        text = self._current_response.strip()
        if not text:
            self._current_response = ""
            self._response_start = None
            return

        timestamp = self._response_start or datetime.now(timezone.utc).isoformat()

        # Check if this is a filler response
        if is_filler(text):
            # Store it to prepend to next response
            if self._pending_filler:
                self._pending_filler += " " + text
            else:
                self._pending_filler = text
                self._pending_filler_timestamp = timestamp
        else:
            # Prepend any pending filler
            if self._pending_filler:
                text = self._pending_filler + " " + text
                timestamp = self._pending_filler_timestamp or timestamp
                self._pending_filler = ""
                self._pending_filler_timestamp = None

            self._transcript.entries.append(
                TranscriptEntry(
                    timestamp=timestamp,
                    speaker="boswell",
                    text=text,
                )
            )

        self._current_response = ""
        self._response_start = None

    def flush(self) -> None:
        """Public flush for end-of-interview cleanup."""
        # Flush current response
        self._flush()
        # Also flush any pending filler
        if self._pending_filler:
            self._transcript.entries.append(
                TranscriptEntry(
                    timestamp=self._pending_filler_timestamp or datetime.now(timezone.utc).isoformat(),
                    speaker="boswell",
                    text=self._pending_filler,
                )
            )
            self._pending_filler = ""
            self._pending_filler_timestamp = None
