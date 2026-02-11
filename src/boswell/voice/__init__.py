"""Voice bot module for Boswell.

Provides real-time voice interview capabilities using Pipecat.
"""

from boswell.voice.acknowledgment import AcknowledgmentProcessor
from boswell.voice.bot import InterviewBot, resume_interview_bot, start_interview_bot
from boswell.voice.bracket_buffer import BracketBufferProcessor
from boswell.voice.mode_detection import ModeDetectionProcessor
from boswell.voice.pipeline import create_pipeline
from boswell.voice.speed_control import SpeedControlProcessor
from boswell.voice.strike_control import StrikeControlProcessor
from boswell.voice.transcript import TranscriptCollector

__all__ = [
    "AcknowledgmentProcessor",
    "BracketBufferProcessor",
    "InterviewBot",
    "ModeDetectionProcessor",
    "SpeedControlProcessor",
    "StrikeControlProcessor",
    "TranscriptCollector",
    "create_pipeline",
    "resume_interview_bot",
    "start_interview_bot",
]
