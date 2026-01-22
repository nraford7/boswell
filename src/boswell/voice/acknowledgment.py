"""Immediate acknowledgment processor for reducing perceived latency."""

import random

from pipecat.frames.frames import (
    Frame,
    TextFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Short acknowledgment phrases to use immediately after user stops speaking
ACKNOWLEDGMENTS = [
    "Mm-hmm.",
    "I see.",
    "Right.",
    "Interesting.",
    "Got it.",
    "Yes.",
    "Okay.",
    "Mm.",
]


class AcknowledgmentProcessor(FrameProcessor):
    """Immediately acknowledges user speech to reduce perceived latency.

    When the user stops speaking, this processor immediately pushes a short
    acknowledgment phrase to the TTS, giving the LLM time to generate a
    fuller response while the user hears immediate feedback.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_acknowledgment = ""

    def _get_acknowledgment(self) -> str:
        """Get a random acknowledgment, avoiding immediate repeats."""
        available = [a for a in ACKNOWLEDGMENTS if a != self._last_acknowledgment]
        ack = random.choice(available)
        self._last_acknowledgment = ack
        return ack

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and inject acknowledgments."""
        await super().process_frame(frame, direction)

        # When user stops speaking, immediately send an acknowledgment
        if isinstance(frame, UserStoppedSpeakingFrame):
            ack = self._get_acknowledgment()
            # Push acknowledgment text frame that will go to TTS
            await self.push_frame(TextFrame(text=ack), FrameDirection.DOWNSTREAM)

        # Always pass the original frame through
        await self.push_frame(frame, direction)
