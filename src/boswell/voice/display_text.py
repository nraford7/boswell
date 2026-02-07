"""Display text processor for sending questions to frontend."""

import logging
import re

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class DisplayTextProcessor(FrameProcessor):
    """Extracts questions from LLM responses and sends to frontend.

    Captures complete LLM responses, extracts the question sentence
    (text ending with ?), and sends it via Daily transport app message.
    """

    def __init__(self, transport, **kwargs):
        """Initialize the processor.

        Args:
            transport: DailyTransport instance for sending app messages.
        """
        super().__init__(**kwargs)
        self._transport = transport
        self._current_text = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames, accumulating text and sending questions."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            self._current_text += frame.text

        elif isinstance(frame, LLMFullResponseEndFrame):
            question = self._extract_question(self._current_text)
            if question:
                await self._send_question(question)
            self._current_text = ""

        await self.push_frame(frame, direction)

    def _extract_question(self, text: str) -> str | None:
        """Extract the last question sentence from text.

        Args:
            text: Full LLM response text.

        Returns:
            The last sentence ending with ?, or None if no question found.
        """
        if not text:
            return None

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())

        # Find the last sentence ending with ?
        for sentence in reversed(sentences):
            sentence = sentence.strip()
            if sentence.endswith('?'):
                return sentence

        return None

    async def _send_question(self, question: str) -> None:
        """Send question to frontend via Daily app message.

        Args:
            question: The question text to display.
        """
        try:
            await self._transport.send_app_message({"question": question})
            logger.debug(f"Sent question to frontend: {question[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to send question to frontend: {e}")
