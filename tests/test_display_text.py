"""Tests for DisplayTextProcessor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipecat.frames.frames import OutputTransportMessageUrgentFrame

from boswell.voice.display_text import DisplayTextProcessor


def _make_processor():
    """Create a DisplayTextProcessor with pipecat internals patched."""
    transport = MagicMock()
    with patch.object(
        DisplayTextProcessor,
        "__init__",
        lambda self, transport=None, **kw: None,
    ):
        proc = DisplayTextProcessor(transport)
    proc._transport = transport
    proc._current_text = ""
    return proc


class TestExtractQuestion:
    """Tests for question extraction logic."""

    def setup_method(self):
        self.processor = _make_processor()

    def test_extracts_last_question(self):
        text = "That's interesting. What do you think about AI?"
        result = self.processor._extract_question(text)
        assert result == "What do you think about AI?"

    def test_extracts_last_of_multiple_questions(self):
        text = "Really? And how does that make you feel?"
        result = self.processor._extract_question(text)
        assert result == "And how does that make you feel?"

    def test_extracts_imperative_prompt_without_question_mark(self):
        text = (
            "That's helpful. "
            "Tell me about your first week on the job."
        )
        result = self.processor._extract_question(text)
        assert result == (
            "Tell me about your first week on the job."
        )

    def test_returns_none_for_no_question(self):
        text = "That's a great point. I agree completely."
        assert self.processor._extract_question(text) is None

    def test_returns_none_for_empty_text(self):
        assert self.processor._extract_question("") is None

    def test_returns_none_for_none(self):
        assert self.processor._extract_question(None) is None

    def test_single_question(self):
        text = "What inspired you to start this project?"
        result = self.processor._extract_question(text)
        assert result == "What inspired you to start this project?"


class TestSummarizeQuestion:
    """Tests for question summary generation."""

    def setup_method(self):
        self.processor = _make_processor()

    def test_keeps_short_question_readable(self):
        q = "What problem are you trying to solve?"
        summary = self.processor._summarize_question(q)
        assert summary == "Problem trying solve"

    def test_converts_to_high_level_summary(self):
        q = (
            "Can you walk me through how your team"
            " evaluates product decisions across"
            " multiple stakeholder groups"
            " and deadlines?"
        )
        summary = self.processor._summarize_question(q)
        assert "team" in summary.lower()

    def test_preserves_conjunction_in_noun_phrase(self):
        q = "How do compensation and benefits differ?"
        summary = self.processor._summarize_question(q)
        assert "benefits" in summary.lower()


class TestSendQuestion:
    """Tests for message sending with correct schema."""

    def setup_method(self):
        self.processor = _make_processor()
        self.processor.push_frame = AsyncMock()

    @pytest.mark.asyncio
    async def test_sends_correct_schema(self):
        await self.processor._send_question(
            "What is your background?"
        )

        self.processor.push_frame.assert_called_once()
        frame = self.processor.push_frame.call_args[0][0]
        assert isinstance(
            frame, OutputTransportMessageUrgentFrame
        )
        assert frame.message["type"] == "display-question"
        assert (
            frame.message["question"]
            == "What is your background?"
        )
        assert "summary" in frame.message

    @pytest.mark.asyncio
    async def test_handles_transport_error(self):
        self.processor.push_frame.side_effect = Exception(
            "connection lost"
        )
        # Should not raise
        await self.processor._send_question("Will this fail?")
