"""Tests for BracketBufferProcessor."""

from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import TextFrame

from boswell.voice.bracket_buffer import BracketBufferProcessor, MAX_BUFFER_SIZE


def _make_processor():
    """Create a BracketBufferProcessor with pipecat internals patched."""
    with patch.object(
        BracketBufferProcessor,
        "__init__",
        lambda self, **kw: None,
    ):
        proc = BracketBufferProcessor()
    proc._buffer = ""
    proc.push_frame = AsyncMock()
    return proc


def _text_frames(proc):
    """Extract text content from all push_frame calls."""
    return [
        call.args[0].text
        for call in proc.push_frame.call_args_list
        if isinstance(call.args[0], TextFrame)
    ]


class TestPassthrough:
    """Normal text should pass through immediately."""

    @pytest.mark.asyncio
    async def test_plain_text(self):
        proc = _make_processor()
        await proc._process_text("Hello world", None)
        assert _text_frames(proc) == ["Hello world"]

    @pytest.mark.asyncio
    async def test_empty_string(self):
        proc = _make_processor()
        await proc._process_text("", None)
        assert _text_frames(proc) == []

    @pytest.mark.asyncio
    async def test_multiple_plain_chunks(self):
        proc = _make_processor()
        await proc._process_text("Hello ", None)
        await proc._process_text("world", None)
        assert _text_frames(proc) == ["Hello ", "world"]


class TestSingleFrameTag:
    """Complete tags in a single frame should pass through as-is."""

    @pytest.mark.asyncio
    async def test_tag_only(self):
        proc = _make_processor()
        await proc._process_text("[STRIKE]", None)
        assert _text_frames(proc) == ["[STRIKE]"]

    @pytest.mark.asyncio
    async def test_tag_with_surrounding_text(self):
        proc = _make_processor()
        await proc._process_text("Sure. [SPEED:slower] Let me continue.", None)
        texts = _text_frames(proc)
        assert texts == ["Sure. ", "[SPEED:slower]", " Let me continue."]

    @pytest.mark.asyncio
    async def test_multiple_tags_in_one_frame(self):
        proc = _make_processor()
        await proc._process_text("[STRIKE][SPEED:normal]", None)
        assert _text_frames(proc) == ["[STRIKE]", "[SPEED:normal]"]


class TestSplitTag:
    """Tags split across multiple chunks should be reassembled."""

    @pytest.mark.asyncio
    async def test_split_across_two_frames(self):
        proc = _make_processor()
        await proc._process_text("Ok. [SPEED", None)
        await proc._process_text(":slower]", None)
        texts = _text_frames(proc)
        assert texts == ["Ok. ", "[SPEED:slower]"]

    @pytest.mark.asyncio
    async def test_split_across_three_frames(self):
        proc = _make_processor()
        await proc._process_text("[SP", None)
        await proc._process_text("EED:", None)
        await proc._process_text("faster] Great.", None)
        texts = _text_frames(proc)
        assert texts == ["[SPEED:faster]", " Great."]

    @pytest.mark.asyncio
    async def test_bracket_open_alone(self):
        proc = _make_processor()
        await proc._process_text("[", None)
        await proc._process_text("STRIKE]", None)
        texts = _text_frames(proc)
        assert texts == ["[STRIKE]"]

    @pytest.mark.asyncio
    async def test_text_before_and_after_split_tag(self):
        proc = _make_processor()
        await proc._process_text("Sure. [MODE", None)
        await proc._process_text(":resume] Welcome back.", None)
        texts = _text_frames(proc)
        assert texts == ["Sure. ", "[MODE:resume]", " Welcome back."]


class TestBufferOverflow:
    """Buffer exceeding max size should flush as-is (not a real tag)."""

    @pytest.mark.asyncio
    async def test_overflow_flushes(self):
        proc = _make_processor()
        # Create content that exceeds MAX_BUFFER_SIZE without closing bracket
        long_content = "[" + "x" * MAX_BUFFER_SIZE
        await proc._process_text(long_content, None)
        texts = _text_frames(proc)
        # The buffer should have been flushed into passthrough
        joined = "".join(texts)
        assert joined == long_content
        # Buffer should be clear
        assert proc._buffer == ""

    @pytest.mark.asyncio
    async def test_overflow_followed_by_normal_text(self):
        proc = _make_processor()
        long_content = "[" + "x" * MAX_BUFFER_SIZE + " more text"
        await proc._process_text(long_content, None)
        joined = "".join(_text_frames(proc))
        assert joined == long_content


class TestLLMEndFlush:
    """LLMFullResponseEndFrame should flush any incomplete buffer."""

    @pytest.mark.asyncio
    async def test_flush_on_end_frame(self):
        proc = _make_processor()
        await proc._process_text("Hello [incomplete", None)
        # Buffer should hold the incomplete tag
        assert proc._buffer == "[incomplete"

        # Simulate LLMFullResponseEndFrame
        await proc._flush(None)
        texts = _text_frames(proc)
        assert texts == ["Hello ", "[incomplete"]
        assert proc._buffer == ""

    @pytest.mark.asyncio
    async def test_no_flush_when_buffer_empty(self):
        proc = _make_processor()
        await proc._process_text("Hello", None)
        call_count_before = proc.push_frame.call_count
        await proc._flush(None)
        # No extra frame pushed
        assert proc.push_frame.call_count == call_count_before


class TestEdgeCases:
    """Edge cases and tricky inputs."""

    @pytest.mark.asyncio
    async def test_nested_brackets(self):
        proc = _make_processor()
        # Inner bracket closes buffer, outer bracket starts new one
        await proc._process_text("[a[b]c]", None)
        texts = _text_frames(proc)
        # First ] closes the buffer at "[a[b]", then "c" passes through,
        # then no new bracket starts since ] is not [
        assert texts == ["[a[b]", "c]"]

    @pytest.mark.asyncio
    async def test_closing_bracket_without_open(self):
        proc = _make_processor()
        await proc._process_text("text] more", None)
        assert _text_frames(proc) == ["text] more"]

    @pytest.mark.asyncio
    async def test_consecutive_tags(self):
        proc = _make_processor()
        await proc._process_text("[A]", None)
        await proc._process_text("[B]", None)
        assert _text_frames(proc) == ["[A]", "[B]"]
