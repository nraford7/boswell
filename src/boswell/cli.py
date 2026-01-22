"""Boswell CLI - Command-line interface for the AI Research Interviewer."""

import typer

app = typer.Typer(
    name="boswell",
    help="AI Research Interviewer - Conduct research-informed interviews autonomously",
    add_completion=False,
)


@app.command()
def init() -> None:
    """Initialize Boswell configuration with API keys."""
    typer.echo("Boswell init - Not yet implemented")


@app.command()
def create(
    topic: str = typer.Option(..., "--topic", "-t", help="Interview topic"),
    docs: str = typer.Option(None, "--docs", "-d", help="Path to research documents"),
    urls: str = typer.Option(None, "--urls", "-u", help="Comma-separated URLs"),
) -> None:
    """Create a new interview session."""
    typer.echo(f"Creating interview for topic: {topic}")
    typer.echo("Boswell create - Not yet implemented")


@app.command()
def status(interview_id: str = typer.Argument(..., help="Interview ID")) -> None:
    """Check the status of an interview."""
    typer.echo(f"Checking status for: {interview_id}")
    typer.echo("Boswell status - Not yet implemented")


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
    typer.echo("Boswell list - Not yet implemented")


if __name__ == "__main__":
    app()
