"""Tests for DisplayTextProcessor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boswell.voice.display_text import DisplayTextProcessor


class TestExtractQuestion:
    """Tests for question extraction logic."""

    def setup_method(self):
        self.transport = MagicMock()
        # Patch FrameProcessor.__init__ to avoid pipecat internals
        with patch.object(DisplayTextProcessor, "__init__", lambda self, transport, **kw: None):
            self.processor = DisplayTextProcessor(self.transport)
        self.processor._transport = self.transport
        self.processor._current_text = ""

    def test_extracts_last_question(self):
        text = "That's interesting. What do you think about AI?"
        assert self.processor._extract_question(text) == "What do you think about AI?"

    def test_extracts_last_of_multiple_questions(self):
        text = "Really? And how does that make you feel?"
        assert self.processor._extract_question(text) == "And how does that make you feel?"

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


class TestSendQuestion:
    """Tests for message sending with correct schema."""

    def setup_method(self):
        self.transport = MagicMock()
        self.transport.send_app_message = AsyncMock()
        with patch.object(DisplayTextProcessor, "__init__", lambda self, transport, **kw: None):
            self.processor = DisplayTextProcessor(self.transport)
        self.processor._transport = self.transport
        self.processor._current_text = ""

    @pytest.mark.asyncio
    async def test_sends_correct_schema(self):
        await self.processor._send_question("What is your background?")
        self.transport.send_app_message.assert_called_once_with(
            {"type": "display-question", "question": "What is your background?"}
        )

    @pytest.mark.asyncio
    async def test_message_includes_type_field(self):
        await self.processor._send_question("Test?")
        call_args = self.transport.send_app_message.call_args[0][0]
        assert call_args["type"] == "display-question"
        assert call_args["question"] == "Test?"

    @pytest.mark.asyncio
    async def test_handles_transport_error(self):
        self.transport.send_app_message.side_effect = Exception("connection lost")
        # Should not raise
        await self.processor._send_question("Will this fail?")
