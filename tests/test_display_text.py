"""Tests for DisplayTextProcessor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipecat.frames.frames import OutputTransportMessageUrgentFrame

from boswell.voice.display_text import DisplayTextProcessor


class TestExtractQuestion:
    """Tests for question extraction logic."""

    def setup_method(self):
        self.transport = MagicMock()
        # Patch FrameProcessor.__init__ to avoid pipecat internals
        with patch.object(DisplayTextProcessor, "__init__", lambda self, transport=None, **kw: None):
            self.processor = DisplayTextProcessor(self.transport)
        self.processor._transport = self.transport
        self.processor._current_text = ""

    def test_extracts_last_question(self):
        text = "That's interesting. What do you think about AI?"
        assert self.processor._extract_question(text) == "What do you think about AI?"

    def test_extracts_last_of_multiple_questions(self):
        text = "Really? And how does that make you feel?"
        assert self.processor._extract_question(text) == "And how does that make you feel?"

    def test_extracts_imperative_prompt_without_question_mark(self):
        text = "That's helpful. Tell me about your first week on the job."
        assert self.processor._extract_question(text) == "Tell me about your first week on the job."

    def test_returns_none_for_no_question(self):
        text = "That's a great point. I agree completely."
        assert self.processor._extract_question(text) is None

    def test_returns_none_for_empty_text(self):
        assert self.processor._extract_question("") is None

    def test_returns_none_for_none(self):
        assert self.processor._extract_question(None) is None

    def test_single_question(self):
        text = "What inspired you to start this project?"
        assert self.processor._extract_question(text) == "What inspired you to start this project?"


class TestSummarizeQuestion:
    """Tests for question summary generation."""

    def setup_method(self):
        self.transport = MagicMock()
        with patch.object(DisplayTextProcessor, "__init__", lambda self, transport=None, **kw: None):
            self.processor = DisplayTextProcessor(self.transport)
        self.processor._transport = self.transport
        self.processor._current_text = ""

    def test_keeps_short_question_readable(self):
        summary = self.processor._summarize_question("What problem are you trying to solve?")
        assert summary == "What problem are you trying to solve"

    def test_truncates_long_question(self):
        summary = self.processor._summarize_question(
            "Can you walk me through how your team evaluates product decisions across multiple stakeholder groups and deadlines?"
        )
        assert summary.endswith("...")
        assert len(summary.split()) <= 14


class TestSendQuestion:
    """Tests for message sending with correct schema."""

    def setup_method(self):
        self.transport = MagicMock()
        with patch.object(DisplayTextProcessor, "__init__", lambda self, transport=None, **kw: None):
            self.processor = DisplayTextProcessor(self.transport)
        self.processor._transport = self.transport
        self.processor._current_text = ""
        self.processor.push_frame = AsyncMock()

    @pytest.mark.asyncio
    async def test_sends_correct_schema(self):
        await self.processor._send_question("What is your background?")

        self.processor.push_frame.assert_called_once()
        frame = self.processor.push_frame.call_args[0][0]
        assert isinstance(frame, OutputTransportMessageUrgentFrame)
        assert frame.message["type"] == "display-question"
        assert frame.message["question"] == "What is your background?"
        assert "summary" in frame.message

    @pytest.mark.asyncio
    async def test_handles_transport_error(self):
        self.processor.push_frame.side_effect = Exception("connection lost")
        # Should not raise
        await self.processor._send_question("Will this fail?")
