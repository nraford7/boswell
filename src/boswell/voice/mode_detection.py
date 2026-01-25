"""Mode detection processor for returning guest interviews."""

import re

from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Pattern to match mode tags: [MODE:resume], [MODE:add_detail], [MODE:fresh_start]
MODE_TAG_PATTERN = re.compile(r"\[MODE:(resume|add_detail|fresh_start)\]", re.IGNORECASE)


class ModeDetectionProcessor(FrameProcessor):
    """Detects interview mode tags in bot responses.

    When the bot includes [MODE:xxx] in its response, this processor
    captures the mode and stores it for the worker to read.
    """

    def __init__(self, on_mode_detected=None, **kwargs):
        super().__init__(**kwargs)
        self._detected_mode: str | None = None
        self._on_mode_detected = on_mode_detected

    @property
    def detected_mode(self) -> str | None:
        """Get the detected interview mode."""
        return self._detected_mode

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames, detecting mode tags."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            match = MODE_TAG_PATTERN.search(frame.text)
            if match:
                self._detected_mode = match.group(1).lower()

                if self._on_mode_detected:
                    await self._on_mode_detected(self._detected_mode)

                # Remove the tag from the text before it goes to TTS
                cleaned_text = MODE_TAG_PATTERN.sub("", frame.text).strip()
                # Push the cleaned frame
                await self.push_frame(TextFrame(text=cleaned_text), direction)
                return

        # Pass through unchanged
        await self.push_frame(frame, direction)
