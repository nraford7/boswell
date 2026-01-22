"""Strike control for removing content from transcripts."""

import re

from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from boswell.voice.transcript import TranscriptCollector


# Pattern to match strike control tag: [STRIKE]
STRIKE_TAG_PATTERN = re.compile(r"\[STRIKE\]", re.IGNORECASE)


class StrikeControlProcessor(FrameProcessor):
    """Processes strike tags from LLM output and marks transcript entries for removal.

    When Claude includes [STRIKE] in its response, this processor strips the tag
    and marks the previous transcript entry (the guest's last statement) for removal.

    Example: "Of course, that's struck from the record. [STRIKE] Now, where were we?"
    becomes: "Of course, that's struck from the record. Now, where were we?"
    and the previous guest statement is marked with struck=True.
    """

    def __init__(self, transcript_collector: TranscriptCollector, **kwargs):
        super().__init__(**kwargs)
        self._transcript = transcript_collector

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames, looking for strike control tags."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            # Check for strike control tag
            if STRIKE_TAG_PATTERN.search(frame.text):
                # Mark the last guest entry as struck
                self._transcript.strike_last_guest_entry()

                # Strip the tag from the text
                cleaned_text = STRIKE_TAG_PATTERN.sub("", frame.text).strip()
                # Push the cleaned frame
                await self.push_frame(TextFrame(text=cleaned_text), direction)
                return

        # Pass through unchanged
        await self.push_frame(frame, direction)
