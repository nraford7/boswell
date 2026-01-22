"""Pipecat pipeline setup for Boswell voice interviews."""

from typing import Any, Callable

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport

from boswell.config import load_config
from boswell.voice.transcript import BotResponseCollector, TranscriptCollector


async def create_pipeline(
    room_url: str,
    room_token: str,
    system_prompt: str,
    bot_name: str = "Boswell",
    on_transcript_update: Callable | None = None,
) -> tuple[PipelineTask, PipelineRunner, TranscriptCollector]:
    """Create a Pipecat pipeline for voice interviews.

    Args:
        room_url: Daily.co room URL.
        room_token: Daily.co room token for bot authentication.
        system_prompt: System prompt for Claude with interview context.
        bot_name: Display name for the bot in the room.
        on_transcript_update: Optional callback for transcript updates.

    Returns:
        Tuple of (PipelineTask, PipelineRunner, TranscriptCollector).

    Raises:
        RuntimeError: If required API keys are not configured.
    """
    config = load_config()
    if config is None:
        raise RuntimeError("Boswell not configured. Run 'boswell init' first.")

    # Validate required API keys
    missing_keys = []
    if not config.claude_api_key:
        missing_keys.append("claude_api_key")
    if not config.deepgram_api_key:
        missing_keys.append("deepgram_api_key")
    if not config.elevenlabs_api_key:
        missing_keys.append("elevenlabs_api_key")

    if missing_keys:
        raise RuntimeError(
            f"Missing required API keys: {', '.join(missing_keys)}. "
            "Run 'boswell init' to configure."
        )

    # Set up Daily transport
    transport = DailyTransport(
        room_url,
        room_token,
        bot_name,
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            transcription_enabled=False,  # We use Deepgram directly
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # Set up STT (Speech-to-Text) with Deepgram
    stt = DeepgramSTTService(
        api_key=config.deepgram_api_key,
        model="nova-2",
        language="en",
    )

    # Set up TTS (Text-to-Speech) with ElevenLabs
    tts = ElevenLabsTTSService(
        api_key=config.elevenlabs_api_key,
        voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel - professional female voice
        model="eleven_turbo_v2",  # Fast model for low latency
        voice_settings={
            "stability": 0.5,
            "similarity_boost": 0.75,
            "speed": 1.15,  # 15% faster speech
        },
    )

    # Set up LLM with Claude
    llm = AnthropicLLMService(
        api_key=config.claude_api_key,
        model="claude-sonnet-4-20250514",
    )

    # Set up conversation context
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    # Set up transcript collection
    transcript_collector = TranscriptCollector()
    bot_response_collector = BotResponseCollector(transcript_collector)

    # Build the pipeline
    # Audio flows: transport.input -> stt -> transcript -> llm -> bot_collector -> tts -> transport.output
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_collector,  # Capture guest speech after STT
            context_aggregator.user(),
            llm,
            bot_response_collector,  # Capture bot responses after LLM
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # Create task with pipeline
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    # Event handlers
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        """Greet the guest when they join."""
        # Trigger the initial greeting with full context
        await task.queue_frames(
            [LLMMessagesFrame([{
                "role": "user",
                "content": "The guest has just joined the room. Follow your OPENING THE INTERVIEW instructions exactly - greet them, explain the interview, mention the timing, tell them about pauses and that they can stop/repeat anytime, then ask if they're ready."
            }])]
        )

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        """End the interview when guest leaves."""
        # Flush any remaining bot response before ending
        bot_response_collector.flush()
        await task.queue_frame(EndFrame())

    @transport.event_handler("on_dialin_ready")
    async def on_dialin_ready(transport, cdata):
        """Handle dial-in ready event."""
        pass

    # Create runner
    runner = PipelineRunner()

    return task, runner, transcript_collector


async def run_interview(
    room_url: str,
    room_token: str,
    system_prompt: str,
    bot_name: str = "Boswell",
) -> list[dict[str, Any]]:
    """Run a voice interview session.

    Args:
        room_url: Daily.co room URL.
        room_token: Daily.co room token.
        system_prompt: System prompt for Claude.
        bot_name: Display name for the bot.

    Returns:
        List of transcript entries as dictionaries.
    """
    task, runner, transcript_collector = await create_pipeline(
        room_url=room_url,
        room_token=room_token,
        system_prompt=system_prompt,
        bot_name=bot_name,
    )

    await runner.run(task)

    # Return collected transcript
    return transcript_collector.get_entries()
