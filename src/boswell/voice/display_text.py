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

SUMMARY_PREFIX_SKIP_WORDS = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "which",
    "can",
    "could",
    "would",
    "will",
    "do",
    "does",
    "did",
    "is",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "tell",
    "walk",
    "talk",
    "take",
    "describe",
    "share",
    "explain",
    "please",
    "me",
    "through",
    "about",
}

SUMMARY_DROP_WORDS = {
    "i",
    "you",
    "your",
    "we",
    "our",
    "me",
    "my",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "will",
    "have",
    "has",
    "had",
    "to",
    "this",
    "that",
    "these",
    "those",
}

MAX_SUMMARY_WORDS = 5


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

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and send question updates at response boundaries."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            self._current_text += frame.text

        elif isinstance(frame, LLMFullResponseEndFrame):
            question = self._extract_question(self._current_text)
            if question:
                await self._send_question(question)
            self._current_text = ""

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
        """Create a short, pithy topic summary for on-screen display."""
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

        words = summary.split()
        while words and words[0].lower() in SUMMARY_PREFIX_SKIP_WORDS:
            words.pop(0)

        filtered_words = [w for w in words if w.lower() not in SUMMARY_DROP_WORDS]
        if filtered_words:
            words = filtered_words

        if not words:
            words = [w for w in re.findall(r"\b[\w']+\b", text) if w]

        pithy = " ".join(words[:MAX_SUMMARY_WORDS]).strip(" ,;")
        if not pithy:
            pithy = question.strip()

        return pithy[0].upper() + pithy[1:] if pithy else question.strip()

    def _normalize_question_sentence(self, question: str) -> str:
        """Normalize text to a single question sentence ending in '?'."""
        text = re.sub(r"\s+", " ", question).strip()
        text = LEADING_FILLER_PATTERN.sub("", text).strip()
        text = text.rstrip(" .!?\n\r\t")
        if not text:
            return question.strip()
        return f"{text}?"

    async def _send_question(self, question: str) -> None:
        """Send question to frontend through transport message frames."""
        normalized_question = self._normalize_question_sentence(question)
        payload = {
            "type": "display-question",
            "question": normalized_question,
            "summary": self._summarize_question(normalized_question),
        }

        try:
            await self.push_frame(
                OutputTransportMessageUrgentFrame(message=payload),
                FrameDirection.DOWNSTREAM,
            )
            logger.debug(f"Sent question to frontend: {question[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to send question to frontend: {e}")
