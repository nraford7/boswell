"""Voice bot module for Boswell.

Provides real-time voice interview capabilities using Pipecat.
"""

from boswell.voice.bot import InterviewBot
from boswell.voice.pipeline import create_pipeline
from boswell.voice.transcript import TranscriptCollector

__all__ = ["InterviewBot", "create_pipeline", "TranscriptCollector"]
