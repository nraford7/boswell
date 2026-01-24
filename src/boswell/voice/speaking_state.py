"""Speaking state processor - emits app messages when bot starts/stops speaking."""

import asyncio
from pipecat.frames.frames import (
    Frame,
    AudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.daily.transport import DailyOutputTransportMessageFrame


class SpeakingStateProcessor(FrameProcessor):
    """Detects when TTS audio starts/stops and emits app messages.

    This processor sits after TTS and before transport.output() to detect
    when audio frames are flowing, then sends app messages so the frontend
    can sync its visualizer with actual speech.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._is_speaking = False
        self._silence_task: asyncio.Task | None = None
        self._silence_timeout = 0.15  # 150ms of no audio = stopped speaking

    async def _emit_speaking_state(self, speaking: bool):
        """Send app message with speaking state."""
        if self._is_speaking != speaking:
            self._is_speaking = speaking
            message = {"type": "speaking_state", "speaking": speaking}
            await self.push_frame(
                DailyOutputTransportMessageFrame(message=message, participant_id=None)
            )

    async def _handle_silence_timeout(self):
        """Called after silence timeout - emit stopped speaking."""
        await asyncio.sleep(self._silence_timeout)
        await self._emit_speaking_state(False)

    def _cancel_silence_timer(self):
        """Cancel pending silence timeout."""
        if self._silence_task and not self._silence_task.done():
            self._silence_task.cancel()
            self._silence_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames, detecting audio activity."""
        await super().process_frame(frame, direction)

        # Detect TTS started - immediately signal speaking
        if isinstance(frame, TTSStartedFrame):
            self._cancel_silence_timer()
            await self._emit_speaking_state(True)

        # Detect TTS stopped - signal stopped speaking
        elif isinstance(frame, TTSStoppedFrame):
            self._cancel_silence_timer()
            await self._emit_speaking_state(False)

        # Audio frames keep us in speaking state
        elif isinstance(frame, AudioRawFrame):
            if not self._is_speaking:
                await self._emit_speaking_state(True)
            # Reset silence timer on each audio frame
            self._cancel_silence_timer()
            self._silence_task = asyncio.create_task(self._handle_silence_timeout())

        # Always forward the frame
        await self.push_frame(frame, direction)
