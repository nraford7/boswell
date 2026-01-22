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
        typer.secho("Interview created successfully!", fg=typer.colors.GREEN)
        typer.echo(f"  ID: {interview.id}")
        typer.echo(f"  Topic: {interview.topic}")
        typer.echo(f"  Questions generated: {len(questions)}")
        typer.echo()
        typer.echo(f"Use 'boswell status {interview.id}' to view details.")

    except RuntimeError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
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

    typer.echo(f"Research docs: {len(interview.research_docs)}")
    typer.echo(f"Research URLs: {len(interview.research_urls)}")
    typer.echo(f"Generated questions: {len(interview.generated_questions)}")
    typer.echo(f"Target time: {interview.target_time_minutes} minutes")
    typer.echo(f"Max time: {interview.max_time_minutes} minutes")

    if interview.output_dir:
        typer.echo(f"Output directory: {interview.output_dir}")


@app.command()
def export(
    interview_id: str = typer.Argument(..., help="Interview ID"),
    output: str = typer.Option("./", "--output", "-o", help="Output directory"),
) -> None:
    """Export interview outputs (transcript, insights, audio)."""
    typer.echo(f"Exporting interview {interview_id} to {output}")
    typer.echo("Boswell export - Not yet implemented")


@app.command()
def retry(interview_id: str = typer.Argument(..., help="Interview ID")) -> None:
    """Retry a no-show interview with a new meeting link."""
    typer.echo(f"Retrying interview: {interview_id}")
    typer.echo("Boswell retry - Not yet implemented")


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
