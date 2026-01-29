"""Audio diagnostics processor for debugging audio flow."""

import logging
from pipecat.frames.frames import (
    Frame,
    AudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class AudioDiagnosticsProcessor(FrameProcessor):
    """Logs audio frame flow for debugging.

    Tracks:
    - Text frames (LLM output)
    - TTS started/stopped
    - Audio raw frames (actual audio data)
    """

    def __init__(self):
        super().__init__()
        self._text_frame_count = 0
        self._tts_started_count = 0
        self._tts_stopped_count = 0
        self._audio_frame_count = 0
        self._total_audio_bytes = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Log frame types as they flow through."""

        if isinstance(frame, TextFrame):
            self._text_frame_count += 1
            logger.info(
                f"[AUDIO-DIAG] TextFrame #{self._text_frame_count}: '{frame.text[:50]}...'"
            )

        elif isinstance(frame, TTSStartedFrame):
            self._tts_started_count += 1
            logger.info(
                f"[AUDIO-DIAG] TTSStartedFrame #{self._tts_started_count}"
            )

        elif isinstance(frame, TTSStoppedFrame):
            self._tts_stopped_count += 1
            logger.info(
                f"[AUDIO-DIAG] TTSStoppedFrame #{self._tts_stopped_count}"
            )

        elif isinstance(frame, AudioRawFrame):
            self._audio_frame_count += 1
            audio_bytes = len(frame.audio) if hasattr(frame, 'audio') else 0
            self._total_audio_bytes += audio_bytes

            # Log every 10th audio frame to avoid spam
            if self._audio_frame_count % 10 == 0:
                logger.info(
                    f"[AUDIO-DIAG] AudioRawFrame #{self._audio_frame_count}: "
                    f"{audio_bytes} bytes (total: {self._total_audio_bytes:,} bytes)"
                )

        # CRITICAL: Handle system frames (StartFrame, etc.) via parent class
        await super().process_frame(frame, direction)
        # Forward all frames to next processor
        await self.push_frame(frame, direction)

    def get_stats(self) -> dict:
        """Get diagnostic statistics."""
        return {
            "text_frames": self._text_frame_count,
            "tts_started": self._tts_started_count,
            "tts_stopped": self._tts_stopped_count,
            "audio_frames": self._audio_frame_count,
            "total_audio_bytes": self._total_audio_bytes,
        }
