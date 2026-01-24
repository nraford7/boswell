"""Pipecat pipeline setup for Boswell voice interviews."""

from typing import Any, Callable

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.services.anthropic.llm import AnthropicLLMContext, AnthropicLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport

from boswell.config import load_config
from boswell.voice.transcript import BotResponseCollector, TranscriptCollector
from boswell.voice.acknowledgment import AcknowledgmentProcessor
from boswell.voice.speed_control import SpeedControlProcessor
from boswell.voice.strike_control import StrikeControlProcessor
# SpeakingStateProcessor disabled - frontend AudioVisualizer disabled due to latency issues
# from boswell.voice.speaking_state import SpeakingStateProcessor


async def create_pipeline(
    room_url: str,
    room_token: str,
    system_prompt: str,
    bot_name: str = "Boswell",
    guest_name: str = "Guest",
    on_transcript_update: Callable | None = None,
    initial_messages: list[dict] | None = None,
) -> tuple[PipelineTask, PipelineRunner, TranscriptCollector, AnthropicLLMContext]:
    """Create a Pipecat pipeline for voice interviews.

    Args:
        room_url: Daily.co room URL.
        room_token: Daily.co room token for bot authentication.
        system_prompt: System prompt for Claude with interview context.
        bot_name: Display name for the bot in the room.
        guest_name: Display name for the guest in transcripts.
        on_transcript_update: Optional callback for transcript updates.
        initial_messages: Optional conversation history for resuming paused interviews.

    Returns:
        Tuple of (PipelineTask, PipelineRunner, TranscriptCollector, AnthropicLLMContext).

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
    # Using Rachel voice (ElevenLabs default) with default settings
    tts = ElevenLabsTTSService(
        api_key=config.elevenlabs_api_key,
        voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel - calm, natural voice
        model="eleven_turbo_v2",  # Fast model for low latency
    )

    # Set up LLM with Claude
    llm = AnthropicLLMService(
        api_key=config.claude_api_key,
        model="claude-sonnet-4-20250514",
    )

    # Set up conversation context with Anthropic-specific system parameter
    if initial_messages:
        # Resume from previous conversation history
        # Extract system message if present in history
        system_msg = system_prompt
        messages = []
        for msg in initial_messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", system_prompt)
            else:
                messages.append(msg)
        context = AnthropicLLMContext(messages=messages, system=system_msg)
    else:
        # Start fresh with system prompt
        context = AnthropicLLMContext(messages=[], system=system_prompt)
    context_aggregator = llm.create_context_aggregator(context)

    # WORKAROUND: Pipecat bug - create_context_aggregator calls from_openai_context()
    # which doesn't copy the system parameter. Re-set it on the actual context.
    actual_context = context_aggregator.user().context
    if initial_messages:
        actual_context.system = system_msg
    else:
        actual_context.system = system_prompt

    # Set up transcript collection
    transcript_collector = TranscriptCollector(guest_name=guest_name)
    bot_response_collector = BotResponseCollector(transcript_collector)

    # Set up immediate acknowledgment for reduced perceived latency
    acknowledgment_processor = AcknowledgmentProcessor()

    # Set up strike control (processes [STRIKE] tags from LLM)
    strike_control_processor = StrikeControlProcessor(transcript_collector)

    # Set up dynamic speed control (processes [SPEED:x] tags from LLM)
    speed_control_processor = SpeedControlProcessor(tts)

    # SpeakingStateProcessor disabled - frontend AudioVisualizer disabled due to latency
    # speaking_state_processor = SpeakingStateProcessor()

    # Build the pipeline
    # Audio flows: transport.input -> stt -> transcript -> ack -> context -> llm -> strike -> speed -> bot_collector -> tts -> output
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_collector,  # Capture guest speech after STT
            acknowledgment_processor,  # Immediate filler acknowledgment
            context_aggregator.user(),
            llm,
            strike_control_processor,  # Process strike tags and mark transcript
            speed_control_processor,  # Process speed tags and adjust TTS
            bot_response_collector,  # Capture bot responses after LLM
            tts,
            # speaking_state_processor,  # Disabled - latency issues
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

    # Track if this is a resumed interview
    is_resumed = initial_messages is not None

    # Track if we've already greeted to prevent double greeting
    greeting_sent = False

    # Event handlers
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        """Greet the guest when they join."""
        nonlocal greeting_sent

        # Prevent double greeting
        if greeting_sent:
            return
        greeting_sent = True

        # Skip if this is the bot itself joining
        participant_info = participant.get("info", {})
        if participant_info.get("isLocal", False):
            greeting_sent = False  # Reset so we greet the actual guest
            return

        # Add greeting message to context and trigger LLM
        # Using OpenAILLMContextFrame with our actual_context preserves the system prompt
        if is_resumed:
            actual_context.add_message({
                "role": "user",
                "content": "Guest rejoined. Welcome back briefly, then continue."
            })
        else:
            actual_context.add_message({
                "role": "user",
                "content": "Guest joined. Briefly introduce yourself as Boswell, mention the interview topic, and ask your first question. Keep the intro to 1-2 sentences."
            })
        await task.queue_frames([OpenAILLMContextFrame(context=actual_context)])

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

    return task, runner, transcript_collector, actual_context


async def run_interview(
    room_url: str,
    room_token: str,
    system_prompt: str,
    bot_name: str = "Boswell",
    guest_name: str = "Guest",
    initial_messages: list[dict] | None = None,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """Run a voice interview session.

    Args:
        room_url: Daily.co room URL.
        room_token: Daily.co room token.
        system_prompt: System prompt for Claude.
        bot_name: Display name for the bot.
        guest_name: Display name for the guest in transcripts.
        initial_messages: Optional conversation history for resuming.

    Returns:
        Tuple of (transcript entries, conversation history).
    """
    task, runner, transcript_collector, context = await create_pipeline(
        room_url=room_url,
        room_token=room_token,
        system_prompt=system_prompt,
        bot_name=bot_name,
        guest_name=guest_name,
        initial_messages=initial_messages,
    )

    await runner.run(task)

    # Return collected transcript and conversation history for potential resume
    return transcript_collector.get_entries(), context.messages
