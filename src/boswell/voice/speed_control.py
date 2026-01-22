"""Dynamic speech speed control for Boswell voice interviews."""

import re

from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService


# Speed presets
SPEED_PRESETS = {
    "slower": 0.85,
    "slow": 0.9,
    "normal": 1.0,
    "fast": 1.15,
    "faster": 1.25,
}

# Pattern to match speed control tags: [SPEED:slower], [SPEED:fast], etc.
SPEED_TAG_PATTERN = re.compile(r"\[SPEED:(slower|slow|normal|fast|faster)\]", re.IGNORECASE)


class SpeedControlProcessor(FrameProcessor):
    """Processes speed control tags from LLM output and adjusts TTS speed.

    When Claude includes a tag like [SPEED:slower] in its response, this
    processor strips the tag and updates the TTS service's speed setting.

    Example: "Of course, I'll slow down a bit. [SPEED:slower] Now, where were we?"
    becomes: "Of course, I'll slow down a bit. Now, where were we?"
    and the TTS speed is adjusted to 0.85x.
    """

    def __init__(self, tts_service: ElevenLabsTTSService, **kwargs):
        super().__init__(**kwargs)
        self._tts = tts_service
        self._current_speed = 1.15  # Default from pipeline config

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames, looking for speed control tags."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            # Check for speed control tag
            match = SPEED_TAG_PATTERN.search(frame.text)
            if match:
                # Extract speed preset
                preset = match.group(1).lower()
                new_speed = SPEED_PRESETS.get(preset, 1.0)

                # Update TTS speed if changed
                if new_speed != self._current_speed:
                    self._current_speed = new_speed
                    # Update the TTS service's voice settings
                    if hasattr(self._tts, "_voice_settings"):
                        self._tts._voice_settings["speed"] = new_speed
                    elif hasattr(self._tts, "voice_settings"):
                        self._tts.voice_settings["speed"] = new_speed

                # Strip the tag from the text
                cleaned_text = SPEED_TAG_PATTERN.sub("", frame.text).strip()
                # Push the cleaned frame
                await self.push_frame(TextFrame(text=cleaned_text), direction)
                return

        # Pass through unchanged
        await self.push_frame(frame, direction)
