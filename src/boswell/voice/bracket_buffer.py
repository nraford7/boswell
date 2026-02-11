"""Bracket buffer processor for reassembling split control tags.

LLM output arrives as individual token chunks, so control tags like
[SPEED:slower] or [STRIKE] often split across multiple TextFrames.
This processor buffers text between '[' and ']' so downstream tag
processors always see complete bracket-delimited tokens.
"""

import logging

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# If a buffer grows past this without finding ']', it's not a real tag.
MAX_BUFFER_SIZE = 64


class BracketBufferProcessor(FrameProcessor):
    """Reassembles bracket-delimited control tags that arrive split across chunks.

    Normal text passes through with zero added latency. When a '[' is
    encountered, characters are buffered until the matching ']' is found,
    then the complete ``[...]`` token is emitted as a single TextFrame.

    A safety valve flushes the buffer if it exceeds MAX_BUFFER_SIZE
    characters without finding ']' (meaning it was never a real tag).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer: str = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            await self._process_text(frame.text, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            await self._flush(direction)

        await self.push_frame(frame, direction)

    async def _process_text(self, text: str, direction: FrameDirection) -> None:
        """Scan text character-by-character, buffering bracket content."""
        passthrough = ""

        for ch in text:
            if self._buffer:
                # Currently buffering inside a bracket
                self._buffer += ch
                if ch == "]":
                    # Bracket complete — emit any queued passthrough first
                    if passthrough:
                        await self.push_frame(TextFrame(text=passthrough), direction)
                        passthrough = ""
                    await self.push_frame(TextFrame(text=self._buffer), direction)
                    self._buffer = ""
                elif len(self._buffer) > MAX_BUFFER_SIZE:
                    # Safety valve: not a real tag, flush everything
                    passthrough += self._buffer
                    self._buffer = ""
            elif ch == "[":
                # Start buffering
                if passthrough:
                    await self.push_frame(TextFrame(text=passthrough), direction)
                    passthrough = ""
                self._buffer = "["
            else:
                passthrough += ch

        if passthrough:
            await self.push_frame(TextFrame(text=passthrough), direction)

    async def _flush(self, direction: FrameDirection) -> None:
        """Flush any incomplete buffer (e.g. at end of LLM response)."""
        if self._buffer:
            await self.push_frame(TextFrame(text=self._buffer), direction)
            self._buffer = ""
