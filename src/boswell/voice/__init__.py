"""Voice bot module for Boswell.

Provides real-time voice interview capabilities using Pipecat.
"""

from boswell.voice.acknowledgment import AcknowledgmentProcessor
from boswell.voice.bot import InterviewBot
from boswell.voice.pipeline import create_pipeline
from boswell.voice.speed_control import SpeedControlProcessor
from boswell.voice.transcript import TranscriptCollector

__all__ = [
    "AcknowledgmentProcessor",
    "InterviewBot",
    "SpeedControlProcessor",
    "create_pipeline",
    "TranscriptCollector",
]
