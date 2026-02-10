"""Display text processor for sending question summaries to frontend."""

import logging
import re

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    OutputTransportMessageUrgentFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


QUESTION_START_PATTERN = re.compile(
    r"^("
    r"who|what|when|where|why|how|which|can|could|would|will|"
    r"do|does|did|is|are|was|were|have|has|had|"
    r"tell me|walk me through|talk me through|describe|share|"
    r"help me understand|explain|give me|take me through"
    r")\b",
    re.IGNORECASE,
)

LEADING_FILLER_PATTERN = re.compile(
    r"^(?:and|so|okay|ok|alright|great|thanks|thank you)[,\s]+",
    re.IGNORECASE,
)

SUMMARY_LEAD_PATTERNS = [
    re.compile(
        r"^(?:can|could|would|will|do|does|did|is|are|was|were|have|has|had)\s+you\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?:tell|walk|talk|take|describe|share|explain)\s+me(?:\s+through)?\s+",
        re.IGNORECASE,
    ),
    re.compile(r"^help\s+me\s+understand\s+", re.IGNORECASE),
]

SUMMARY_SPLIT_PATTERN = re.compile(
    r"(?:,|;|\s+and\s+|\s+or\s+|\s+because\s+|\s+so that\s+)",
    re.IGNORECASE,
)


class DisplayTextProcessor(FrameProcessor):
    """Extracts questions from LLM responses and sends them to frontend.

    Captures streamed LLM text, detects question-like prompts, and sends both
    full question text and a short summary via transport app-message frames.
    """

    def __init__(self, transport=None, **kwargs):
        """Initialize the processor.

        Args:
            transport: Kept for backward compatibility. Unused.
        """
        super().__init__(**kwargs)
        self._transport = transport
        self._current_text = ""
        self._last_sent_question = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames, streaming question updates to frontend."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            self._current_text += frame.text
            await self._maybe_send_latest_question()

        elif isinstance(frame, LLMFullResponseEndFrame):
            # Final fallback check at response boundary.
            await self._maybe_send_latest_question()
            self._current_text = ""
            self._last_sent_question = ""

        await self.push_frame(frame, direction)

    def _extract_question(self, text: str | None) -> str | None:
        """Extract the latest question-like sentence from text."""
        if not text:
            return None

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.strip())
            if sentence and sentence.strip()
        ]
        if not sentences:
            return None

        # Prefer explicit questions ending with '?'.
        for sentence in reversed(sentences):
            if sentence.endswith("?"):
                return sentence

        # Fallback for imperative/interrogative prompts without '?'.
        for sentence in reversed(sentences):
            if QUESTION_START_PATTERN.match(sentence):
                return sentence

        return None

    def _summarize_question(self, question: str) -> str:
        """Create a high-level, readable summary for on-screen display."""
        text = re.sub(r"\s+", " ", question).strip()
        text = LEADING_FILLER_PATTERN.sub("", text).strip()
        text = text.rstrip("?!. ")

        if not text:
            return question.strip()

        for pattern in SUMMARY_LEAD_PATTERNS:
            text = pattern.sub("", text).strip()

        # Keep the first high-level clause and drop trailing detail.
        parts = SUMMARY_SPLIT_PATTERN.split(text, maxsplit=1)
        summary = parts[0].strip(" ,;")
        if not summary:
            summary = text

        return summary[0].upper() + summary[1:] if summary else question.strip()

    async def _maybe_send_latest_question(self) -> None:
        """Detect and send new question text if it changed."""
        question = self._extract_question(self._current_text)
        if not question or question == self._last_sent_question:
            return

        await self._send_question(question)
        self._last_sent_question = question

    async def _send_question(self, question: str) -> None:
        """Send question to frontend through transport message frames."""
        payload = {
            "type": "display-question",
            "question": question,
            "summary": self._summarize_question(question),
        }

        try:
            await self.push_frame(
                OutputTransportMessageUrgentFrame(message=payload),
                FrameDirection.DOWNSTREAM,
            )
            logger.debug(f"Sent question to frontend: {question[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to send question to frontend: {e}")
