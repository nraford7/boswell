"""Boswell CLI - Command-line interface for the AI Research Interviewer."""

import typer

from boswell.config import (
    BoswellConfig,
    get_config_path,
    load_config,
    save_config,
    validate_api_keys,
)
from boswell.ingestion import ingest_research
from boswell.interview import (
    InterviewStatus,
    create_interview,
    load_interview,
    save_interview,
)
from boswell.interview import list_interviews as get_all_interviews
from boswell.meeting import (
    NO_SHOW_TIMEOUT_MINUTES,
    MeetingBaaSError,
    create_interview_bot,
    handle_no_show,
    validate_meeting_url,
    wait_for_guest_sync,
)
from boswell.output import export_interview, generate_output_path

app = typer.Typer(
    name="boswell",
    help="AI Research Interviewer - Conduct research-informed interviews autonomously",
    add_completion=False,
)


def _prompt_api_key(name: str, current_value: str, required: bool = True) -> str:
    """Prompt for an API key with optional/required indicator.

    Args:
        name: Human-readable name of the API key.
        current_value: Current value (shown as masked if set).
        required: Whether this key is required.

    Returns:
        The entered API key, or current value if empty input.
    """
    status = "[required]" if required else "[optional]"
    if current_value:
        # Show masked version of current key
        if len(current_value) > 8:
            masked = current_value[:4] + "..." + current_value[-4:]
        else:
            masked = "***"
        prompt_text = f"{name} {status} (current: {masked})"
    else:
        prompt_text = f"{name} {status}"

    value = typer.prompt(prompt_text, default="", show_default=False)
    # If user entered empty, keep current value
    return value if value else current_value


@app.command()
def init() -> None:
    """Initialize Boswell configuration with API keys."""
    typer.echo("Boswell Configuration Setup")
    typer.echo("=" * 40)
    typer.echo()

    # Load existing config if present
    existing_config = load_config()
    if existing_config:
        typer.echo(f"Existing config found at {get_config_path()}")
        typer.echo("Press Enter to keep current values, or enter new values.")
        typer.echo()
    else:
        existing_config = BoswellConfig()
        typer.echo("No existing config found. Creating new configuration.")
        typer.echo("Press Enter to skip optional fields.")
        typer.echo()

    # Prompt for API keys
    typer.echo("API Keys:")
    typer.echo("-" * 20)

    claude_key = _prompt_api_key(
        "Claude API Key", existing_config.claude_api_key, required=True
    )
    elevenlabs_key = _prompt_api_key(
        "ElevenLabs API Key", existing_config.elevenlabs_api_key, required=True
    )
    deepgram_key = _prompt_api_key(
        "Deepgram API Key", existing_config.deepgram_api_key, required=True
    )
    meetingbaas_key = _prompt_api_key(
        "MeetingBaaS API Key", existing_config.meetingbaas_api_key, required=True
    )

    typer.echo()
    typer.echo("Settings:")
    typer.echo("-" * 20)

    # Meeting provider selection
    meeting_provider = typer.prompt(
        "Meeting provider (google_meet/zoom)",
        default=existing_config.meeting_provider,
    )

    # Interview time settings
    target_time = typer.prompt(
        "Default target interview time (minutes)",
        default=existing_config.default_target_time,
        type=int,
    )

    max_time = typer.prompt(
        "Default max interview time (minutes)",
        default=existing_config.default_max_time,
        type=int,
    )

    # Create and save config
    config = BoswellConfig(
        claude_api_key=claude_key,
        elevenlabs_api_key=elevenlabs_key,
        deepgram_api_key=deepgram_key,
        meetingbaas_api_key=meetingbaas_key,
        meeting_provider=meeting_provider,
        default_target_time=target_time,
        default_max_time=max_time,
    )

    save_config(config)

    typer.echo()
    typer.echo("=" * 40)
    typer.echo(f"Configuration saved to {get_config_path()}")

    # Show validation status
    key_status = validate_api_keys(config)
    typer.echo()
    typer.echo("API Key Status:")
    for key_name, is_set in key_status.items():
        status_icon = "[set]" if is_set else "[not set]"
        typer.echo(f"  {key_name}: {status_icon}")

    # Warn about missing required keys
    missing_required = [k for k, v in key_status.items() if not v]
    if missing_required:
        typer.echo()
        typer.secho(
            "Warning: Some API keys are not set. You may need to configure them "
            "before running interviews.",
            fg=typer.colors.YELLOW,
        )


@app.command()
def create(
    topic: str = typer.Option(..., "--topic", "-t", help="Interview topic"),
    docs: str = typer.Option(
        None, "--docs", "-d", help="Comma-separated paths to research documents"
    ),
    urls: str = typer.Option(None, "--urls", "-u", help="Comma-separated URLs"),
) -> None:
    """Create a new interview session."""
    typer.echo(f"Creating interview for topic: {topic}")

    # Parse documents and URLs
    doc_list: list[str] = []
    url_list: list[str] = []

    if docs:
        doc_list = [d.strip() for d in docs.split(",") if d.strip()]
        typer.echo(f"Research documents: {len(doc_list)}")

    if urls:
        url_list = [u.strip() for u in urls.split(",") if u.strip()]
        typer.echo(f"Research URLs: {len(url_list)}")

    # Check if config exists for question generation
    config = load_config()
    if config is None or not config.claude_api_key:
        typer.secho(
            "Warning: Claude API key not configured. Cannot generate questions.",
            fg=typer.colors.YELLOW,
        )
        typer.echo("Run 'boswell init' to configure, then create the interview.")
        raise typer.Exit(1)

    typer.echo()
    typer.echo("Processing research materials...")

    try:
        # Ingest research and generate questions
        aggregated_content, questions = ingest_research(topic, doc_list, url_list)

        # Create the interview
        interview = create_interview(topic=topic, docs=doc_list, urls=url_list)

        # Update interview with generated questions
        interview.generated_questions = questions
        save_interview(interview)

        typer.echo()
        typer.secho("Questions generated successfully!", fg=typer.colors.GREEN)
        typer.echo(f"  Questions generated: {len(questions)}")
        typer.echo()

        # Prompt for meeting URL
        typer.echo("-" * 40)
        typer.echo("Now we need a meeting link for the interview.")
        typer.echo("Create a Google Meet or Zoom meeting and paste the URL below.")
        typer.echo()

        while True:
            meeting_url = typer.prompt(
                "Meeting URL (Google Meet or Zoom)",
                default="",
                show_default=False,
            )

            if not meeting_url.strip():
                typer.secho(
                    "Meeting URL is required to dispatch the interview bot.",
                    fg=typer.colors.YELLOW,
                )
                skip = typer.confirm("Skip bot creation for now?", default=False)
                if skip:
                    typer.echo()
                    typer.secho(
                        "Interview created without bot.", fg=typer.colors.YELLOW
                    )
                    typer.echo(f"  ID: {interview.id}")
                    typer.echo(f"  Topic: {interview.topic}")
                    typer.echo()
                    typer.echo(
                        "Add a meeting URL later with 'boswell retry "
                        f"{interview.id}'"
                    )
                    return
                continue

            if not validate_meeting_url(meeting_url):
                typer.secho(
                    "Invalid meeting URL. Please provide a Google Meet, Zoom, or "
                    "Teams URL.",
                    fg=typer.colors.RED,
                )
                continue

            break

        # Update interview with meeting link
        interview.meeting_link = meeting_url.strip()
        save_interview(interview)

        # Create the MeetingBaaS bot
        typer.echo()
        typer.echo("Creating interview bot...")

        # Check MeetingBaaS API key
        if config is None or not config.meetingbaas_api_key:
            typer.secho(
                "Warning: MeetingBaaS API key not configured. Cannot create bot.",
                fg=typer.colors.YELLOW,
            )
            typer.echo("Run 'boswell init' to configure, then use 'boswell retry'.")
            typer.echo()
            typer.echo(f"Interview ID: {interview.id}")
            typer.echo(f"Meeting link saved: {interview.meeting_link}")
            return

        try:
            bot_id = create_interview_bot(interview)
            interview.bot_id = bot_id
            interview.status = InterviewStatus.WAITING
            save_interview(interview)

            typer.echo()
            typer.secho("Interview ready!", fg=typer.colors.GREEN)
            typer.echo("=" * 40)
            typer.echo(f"  ID: {interview.id}")
            typer.echo(f"  Topic: {interview.topic}")
            typer.echo(f"  Questions: {len(questions)}")
            typer.echo(f"  Bot ID: {bot_id}")
            typer.echo()
            typer.echo("Share this link with your guest:")
            typer.secho(f"  {interview.meeting_link}", fg=typer.colors.CYAN)
            typer.echo()
            typer.echo(f"Check status: boswell status {interview.id}")

        except MeetingBaaSError as e:
            typer.secho(f"Failed to create bot: {e}", fg=typer.colors.RED)
            typer.echo("The interview was saved. Try again with 'boswell retry'.")
            typer.echo(f"Interview ID: {interview.id}")
            raise typer.Exit(1)

    except RuntimeError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except MeetingBaaSError as e:
        typer.secho(f"MeetingBaaS error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Failed to create interview: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def status(interview_id: str = typer.Argument(..., help="Interview ID")) -> None:
    """Check the status of an interview."""
    interview = load_interview(interview_id)

    if interview is None:
        typer.secho(f"Interview not found: {interview_id}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"Interview: {interview.id}")
    typer.echo("-" * 40)
    typer.echo(f"Topic: {interview.topic}")

    # Color-code the status
    status_colors = {
        InterviewStatus.PENDING: typer.colors.YELLOW,
        InterviewStatus.WAITING: typer.colors.CYAN,
        InterviewStatus.IN_PROGRESS: typer.colors.BLUE,
        InterviewStatus.PROCESSING: typer.colors.MAGENTA,
        InterviewStatus.COMPLETE: typer.colors.GREEN,
        InterviewStatus.NO_SHOW: typer.colors.RED,
        InterviewStatus.ERROR: typer.colors.RED,
    }
    color = status_colors.get(interview.status, typer.colors.WHITE)
    typer.echo("Status: ", nl=False)
    typer.secho(interview.status.value, fg=color)

    typer.echo(f"Created: {interview.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    if interview.started_at:
        typer.echo(
            f"Started: {interview.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
    if interview.completed_at:
        typer.echo(
            f"Completed: {interview.completed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

    if interview.guest_name:
        typer.echo(f"Guest: {interview.guest_name}")

    if interview.meeting_link:
        typer.echo(f"Meeting link: {interview.meeting_link}")

    if interview.bot_id:
        typer.echo(f"Bot ID: {interview.bot_id}")

    typer.echo(f"Research docs: {len(interview.research_docs)}")
    typer.echo(f"Research URLs: {len(interview.research_urls)}")
    typer.echo(f"Generated questions: {len(interview.generated_questions)}")
    typer.echo(f"Target time: {interview.target_time_minutes} minutes")
    typer.echo(f"Max time: {interview.max_time_minutes} minutes")

    if interview.output_dir:
        typer.echo(f"Output directory: {interview.output_dir}")


@app.command()
def wait(
    interview_id: str = typer.Argument(..., help="Interview ID"),
    timeout: int = typer.Option(
        NO_SHOW_TIMEOUT_MINUTES,
        "--timeout",
        "-t",
        help="Timeout in minutes",
    ),
) -> None:
    """Wait for guest to join the interview meeting.

    Polls the bot status every 30 seconds until the guest joins or timeout.
    Updates interview status to IN_PROGRESS when guest joins, or NO_SHOW on timeout.
    """
    interview = load_interview(interview_id)

    if interview is None:
        typer.secho(f"Interview not found: {interview_id}", fg=typer.colors.RED)
        raise typer.Exit(1)

    if not interview.bot_id:
        typer.secho(
            f"Interview {interview_id} has no bot dispatched. "
            "Run 'boswell retry' to create a bot first.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    if interview.status == InterviewStatus.IN_PROGRESS:
        typer.secho(
            "Guest already joined! Interview is in progress.", fg=typer.colors.GREEN
        )
        return

    if interview.status == InterviewStatus.COMPLETE:
        typer.secho("Interview is already complete.", fg=typer.colors.CYAN)
        return

    if interview.status == InterviewStatus.NO_SHOW:
        typer.secho(
            "Interview was marked as no-show. Use 'boswell retry' to reschedule.",
            fg=typer.colors.YELLOW,
        )
        return

    typer.echo(f"Waiting for guest to join interview: {interview_id}")
    typer.echo(f"Topic: {interview.topic}")
    typer.echo(f"Timeout: {timeout} minutes")
    typer.echo()
    typer.echo("Share this link with your guest:")
    typer.secho(f"  {interview.meeting_link}", fg=typer.colors.CYAN)
    typer.echo()
    typer.echo("Press Ctrl+C to cancel.")
    typer.echo()

    def progress_callback(elapsed_seconds: int, remaining_seconds: int) -> None:
        """Display progress during wait."""
        elapsed_min = elapsed_seconds // 60
        elapsed_sec = elapsed_seconds % 60
        remaining_min = remaining_seconds // 60
        remaining_sec = remaining_seconds % 60
        typer.echo(
            f"  Waiting... {elapsed_min:02d}:{elapsed_sec:02d} elapsed, "
            f"{remaining_min:02d}:{remaining_sec:02d} remaining",
        )

    try:
        guest_joined = wait_for_guest_sync(
            interview_id,
            timeout_minutes=timeout,
            progress_callback=progress_callback,
        )

        typer.echo()
        if guest_joined:
            typer.secho(
                "Guest joined! Interview is now IN_PROGRESS.", fg=typer.colors.GREEN
            )
            typer.echo(f"Check status: boswell status {interview_id}")
        else:
            # Handle no-show
            handle_no_show(interview_id)
            typer.secho(
                f"Timeout: Guest did not join within {timeout} minutes.",
                fg=typer.colors.RED,
            )
            typer.echo()
            typer.echo("Interview marked as NO_SHOW.")
            typer.echo("To reschedule with a new meeting link:")
            typer.secho(f"  boswell retry {interview_id}", fg=typer.colors.CYAN)

    except ValueError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except RuntimeError as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo()
        typer.secho("Wait cancelled by user.", fg=typer.colors.YELLOW)
        typer.echo(
            f"Interview status unchanged. Check with: boswell status {interview_id}"
        )
        raise typer.Exit(0)
    except MeetingBaaSError as e:
        typer.secho(f"MeetingBaaS error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def export(
    interview_id: str = typer.Argument(..., help="Interview ID"),
    output: str = typer.Option(None, "--output", "-o", help="Output directory"),
    transcript_file: str = typer.Option(
        None, "--transcript", "-t", help="Path to raw transcript JSON file"
    ),
) -> None:
    """Export interview outputs (transcript.md and insights.md).

    Processes raw interview transcripts into clean markdown with insights.
    Requires a completed interview and transcript data.
    """
    import json
    from pathlib import Path

    # Load the interview
    interview = load_interview(interview_id)
    if interview is None:
        typer.secho(f"Interview not found: {interview_id}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"Exporting interview: {interview_id}")
    typer.echo(f"Topic: {interview.topic}")
    typer.echo()

    # Check config for Claude API key
    config = load_config()
    if config is None or not config.claude_api_key:
        typer.secho(
            "Claude API key not configured. Run 'boswell init' first.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # Load transcript data
    raw_transcript: list[dict] = []

    if transcript_file:
        transcript_path = Path(transcript_file)
        if not transcript_path.exists():
            typer.secho(
                f"Transcript file not found: {transcript_file}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        try:
            raw_transcript = json.loads(transcript_path.read_text())
            if not isinstance(raw_transcript, list):
                typer.secho(
                    "Transcript file must contain a JSON array of entries.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            typer.echo(f"Loaded transcript: {len(raw_transcript)} entries")
        except json.JSONDecodeError as e:
            typer.secho(f"Invalid JSON in transcript file: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
    else:
        # For now, require transcript file
        # Future: load from stored conversation state
        typer.secho(
            "Transcript file required. Use --transcript/-t to specify path.",
            fg=typer.colors.RED,
        )
        typer.echo()
        typer.echo("Example: boswell export int_abc123 -t transcript.json")
        raise typer.Exit(1)

    # Determine output directory
    if output:
        output_dir = Path(output)
    else:
        # Generate default output path
        date_str = interview.created_at.strftime("%Y-%m-%d")
        output_dir = generate_output_path(
            interview_id=interview.id,
            guest_name=interview.guest_name,
            date=date_str,
        )

    typer.echo(f"Output directory: {output_dir}")
    typer.echo()

    # Process and export
    typer.echo("Processing transcript...")
    try:
        transcript_path, insights_path = export_interview(
            interview_id=interview_id,
            output_dir=output_dir,
            raw_transcript=raw_transcript,
        )

        typer.echo()
        typer.secho("Export complete!", fg=typer.colors.GREEN)
        typer.echo("=" * 40)
        typer.echo(f"Transcript: {transcript_path}")
        typer.echo(f"Insights:   {insights_path}")
        typer.echo()
        typer.echo("Interview output_dir updated.")

    except RuntimeError as e:
        typer.secho(f"Export failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except ValueError as e:
        typer.secho(f"Export failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def retry(interview_id: str = typer.Argument(..., help="Interview ID")) -> None:
    """Retry a no-show interview with a new meeting link."""
    interview = load_interview(interview_id)

    if interview is None:
        typer.secho(f"Interview not found: {interview_id}", fg=typer.colors.RED)
        raise typer.Exit(1)

    # Allow retry for pending, no_show, or error status
    if interview.status not in (
        InterviewStatus.PENDING,
        InterviewStatus.NO_SHOW,
        InterviewStatus.ERROR,
    ):
        typer.secho(
            f"Cannot retry interview with status: {interview.status.value}",
            fg=typer.colors.RED,
        )
        typer.echo("Retry is only available for pending, no_show, or error interviews.")
        raise typer.Exit(1)

    typer.echo(f"Retrying interview: {interview_id}")
    typer.echo(f"Topic: {interview.topic}")
    typer.echo()

    # Check config
    config = load_config()
    if config is None or not config.meetingbaas_api_key:
        typer.secho(
            "MeetingBaaS API key not configured. Run 'boswell init' first.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # Prompt for new meeting URL
    typer.echo("Enter a new meeting URL for the interview.")
    if interview.meeting_link:
        typer.echo(f"Previous URL: {interview.meeting_link}")
    typer.echo()

    while True:
        meeting_url = typer.prompt(
            "New meeting URL (Google Meet or Zoom)",
            default="",
            show_default=False,
        )

        if not meeting_url.strip():
            typer.secho("Meeting URL is required.", fg=typer.colors.YELLOW)
            continue

        if not validate_meeting_url(meeting_url):
            typer.secho(
                "Invalid meeting URL. Provide a Google Meet, Zoom, or Teams URL.",
                fg=typer.colors.RED,
            )
            continue

        break

    # Update interview with new meeting link
    interview.meeting_link = meeting_url.strip()
    save_interview(interview)

    typer.echo()
    typer.echo("Creating interview bot...")

    try:
        bot_id = create_interview_bot(interview)
        interview.bot_id = bot_id
        interview.status = InterviewStatus.WAITING
        save_interview(interview)

        typer.echo()
        typer.secho("Interview ready!", fg=typer.colors.GREEN)
        typer.echo("=" * 40)
        typer.echo(f"  ID: {interview.id}")
        typer.echo(f"  Bot ID: {bot_id}")
        typer.echo()
        typer.echo("Share this link with your guest:")
        typer.secho(f"  {interview.meeting_link}", fg=typer.colors.CYAN)
        typer.echo()
        typer.echo(f"Check status: boswell status {interview.id}")

    except MeetingBaaSError as e:
        typer.secho(f"Failed to create bot: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command(name="list")
def list_interviews() -> None:
    """List all past interviews."""
    interviews = get_all_interviews()

    if not interviews:
        typer.echo("No interviews found.")
        typer.echo("Create one with: boswell create --topic 'Your topic'")
        return

    typer.echo(f"Found {len(interviews)} interview(s):")
    typer.echo()

    # Define status colors
    status_colors = {
        InterviewStatus.PENDING: typer.colors.YELLOW,
        InterviewStatus.WAITING: typer.colors.CYAN,
        InterviewStatus.IN_PROGRESS: typer.colors.BLUE,
        InterviewStatus.PROCESSING: typer.colors.MAGENTA,
        InterviewStatus.COMPLETE: typer.colors.GREEN,
        InterviewStatus.NO_SHOW: typer.colors.RED,
        InterviewStatus.ERROR: typer.colors.RED,
    }

    for interview in interviews:
        # Format: ID | Status | Topic | Date
        color = status_colors.get(interview.status, typer.colors.WHITE)
        date_str = interview.created_at.strftime("%Y-%m-%d %H:%M")

        typer.echo(f"  {interview.id}  ", nl=False)
        typer.secho(f"{interview.status.value:12}", fg=color, nl=False)
        typer.echo(f"  {date_str}  {interview.topic[:40]}")

    typer.echo()
    typer.echo("Use 'boswell status <id>' for details.")


if __name__ == "__main__":
    app()
