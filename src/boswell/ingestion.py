"""Research ingestion for Boswell.

Handles processing of research documents and URLs to generate interview questions.
No vector DB, no embeddings - pass content directly to Claude.
"""

from pathlib import Path

from pydantic import BaseModel, Field


class ResearchMaterial(BaseModel):
    """Processed research material ready for Claude."""

    source: str = Field(..., description="Source path or URL")
    content: str = Field(..., description="Extracted text content")
    source_type: str = Field(..., description="Type: 'document' or 'url'")


class IngestedResearch(BaseModel):
    """Collection of processed research materials."""

    materials: list[ResearchMaterial] = Field(default_factory=list)
    total_tokens_estimate: int = Field(default=0)


def process_document(path: Path) -> ResearchMaterial | None:
    """Process a local document (PDF, text, etc.) into research material.

    Args:
        path: Path to the document

    Returns:
        ResearchMaterial if successfully processed, None otherwise
    """
    # TODO: Implement document processing
    # Claude can read PDFs natively - extract and pass content directly
    raise NotImplementedError("Document processing not yet implemented")


def process_url(url: str) -> ResearchMaterial | None:
    """Fetch and process a URL into research material.

    Args:
        url: URL to fetch and process

    Returns:
        ResearchMaterial if successfully processed, None otherwise
    """
    # TODO: Implement URL fetching and processing
    raise NotImplementedError("URL processing not yet implemented")


def ingest_research(
    doc_paths: list[Path] | None = None,
    urls: list[str] | None = None,
) -> IngestedResearch:
    """Process all research materials for an interview.

    Args:
        doc_paths: List of document paths to process
        urls: List of URLs to fetch and process

    Returns:
        IngestedResearch containing all processed materials
    """
    # TODO: Implement full ingestion pipeline
    raise NotImplementedError("Research ingestion not yet implemented")


def generate_questions(research: IngestedResearch, topic: str) -> list[str]:
    """Generate interview questions from research materials.

    Uses Claude to analyze research and generate relevant questions.

    Args:
        research: Processed research materials
        topic: Interview topic

    Returns:
        List of generated interview questions
    """
    # TODO: Implement question generation via Claude
    raise NotImplementedError("Question generation not yet implemented")
