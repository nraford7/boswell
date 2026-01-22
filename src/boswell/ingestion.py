"""Research ingestion for Boswell.

Handles processing of research documents and URLs to generate interview questions.
No vector DB, no embeddings - pass content directly to Claude.
"""

import html.parser
import re
from pathlib import Path

import anthropic
import httpx
from pydantic import BaseModel, Field

from boswell.config import load_config


class ResearchMaterial(BaseModel):
    """Processed research material ready for Claude."""

    source: str = Field(..., description="Source path or URL")
    content: str = Field(..., description="Extracted text content")
    source_type: str = Field(..., description="Type: 'document' or 'url'")


class IngestedResearch(BaseModel):
    """Collection of processed research materials."""

    materials: list[ResearchMaterial] = Field(default_factory=list)
    total_tokens_estimate: int = Field(default=0)


class HTMLTextExtractor(html.parser.HTMLParser):
    """Simple HTML to text extractor."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._skip_data = False
        self._skip_tags = {"script", "style", "head", "meta", "link", "noscript"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._skip_tags:
            self._skip_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip_tags:
            self._skip_data = False
        # Add newlines for block elements
        if tag.lower() in {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_data:
            self.text_parts.append(data)

    def get_text(self) -> str:
        """Get extracted text, cleaned up."""
        text = "".join(self.text_parts)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        # Restore paragraph breaks
        text = re.sub(r" ?\n ?", "\n", text)
        # Remove excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def read_text_file(path: Path) -> str:
    """Read .txt, .md files.

    Args:
        path: Path to the text file.

    Returns:
        Contents of the file as a string.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file extension is not supported.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix not in {".txt", ".md"}:
        raise ValueError(f"Unsupported file type: {suffix}. Expected .txt or .md")

    return path.read_text(encoding="utf-8")


def read_pdf_file(path: Path) -> str:
    """Read PDF files using pypdf.

    Args:
        path: Path to the PDF file.

    Returns:
        Extracted text from all pages.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is not a PDF.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected PDF file, got: {path.suffix}")

    from pypdf import PdfReader

    reader = PdfReader(path)
    text_parts = []

    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)

    return "\n\n".join(text_parts)


def read_document(path: Path) -> str:
    """Route to appropriate reader based on file extension.

    Args:
        path: Path to the document.

    Returns:
        Extracted text content.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file type is not supported.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return read_text_file(path)
    elif suffix == ".pdf":
        return read_pdf_file(path)
    else:
        raise ValueError(
            f"Unsupported document type: {suffix}. Supported: .txt, .md, .pdf"
        )


def fetch_url(url: str) -> str:
    """Fetch URL content and extract text from HTML.

    Args:
        url: The URL to fetch.

    Returns:
        Extracted text content from the page.

    Raises:
        httpx.HTTPError: If the request fails.
        ValueError: If the URL scheme is not http or https.
    """
    # Validate URL scheme to prevent SSRF attacks
    parsed = url.lower()
    if not (parsed.startswith("http://") or parsed.startswith("https://")):
        raise ValueError(
            f"Invalid URL scheme. Only http:// and https:// are allowed: {url}"
        )

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "Boswell/1.0"})
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()

    # If it's plain text, return as-is
    if "text/plain" in content_type:
        return response.text

    # For HTML, extract text
    if "text/html" in content_type or not content_type:
        extractor = HTMLTextExtractor()
        try:
            extractor.feed(response.text)
        except Exception:
            # Fallback: strip all HTML tags with regex
            text = re.sub(r"<[^>]+>", " ", response.text)
            text = re.sub(r"\s+", " ", text)
            return text.strip()
        return extractor.get_text()

    # For other types, return raw text
    return response.text


def aggregate_research(docs: list[str], urls: list[str]) -> str:
    """Combine all research into one text blob.

    Args:
        docs: List of document paths to read.
        urls: List of URLs to fetch.

    Returns:
        Concatenated content with source labels.
    """
    sections = []

    # Process documents
    for doc_path in docs:
        path = Path(doc_path)
        try:
            content = read_document(path)
            sections.append(f"=== Document: {path.name} ===\n{content}")
        except Exception as e:
            sections.append(f"=== Document: {path.name} ===\n[Error reading: {e}]")

    # Process URLs
    for url in urls:
        try:
            content = fetch_url(url)
            sections.append(f"=== URL: {url} ===\n{content}")
        except Exception as e:
            sections.append(f"=== URL: {url} ===\n[Error fetching: {e}]")

    return "\n\n".join(sections)


def generate_questions(
    topic: str,
    research_content: str,
    num_questions: int = 12,
) -> list[str]:
    """Generate interview questions using Claude API.

    Args:
        topic: The interview topic.
        research_content: Aggregated research content.
        num_questions: Number of questions to generate (default 12).

    Returns:
        List of generated interview questions.

    Raises:
        RuntimeError: If config is not found or API key is missing.
    """
    config = load_config()
    if config is None or not config.claude_api_key:
        raise RuntimeError(
            "Claude API key not configured. Run 'boswell init' to set up."
        )

    client = anthropic.Anthropic(api_key=config.claude_api_key)

    prompt = f"""You are helping prepare for a research interview about: {topic}

Based on the following research materials, generate {num_questions} thoughtful
interview questions.

The questions should:
1. Be open-ended to encourage detailed responses
2. Build from foundational to more nuanced topics
3. Reference specific details from the research where relevant
4. Include follow-up prompts where appropriate
5. Be natural and conversational in tone

Research materials:
{research_content if research_content.strip() else "[No research materials provided]"}

Generate exactly {num_questions} questions, one per line, numbered 1-{num_questions}.
Focus on questions that will elicit interesting, substantive responses."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text from response
    response_text = response.content[0].text

    # Parse numbered questions
    questions = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line:
            # Remove numbering like "1.", "1)", "1:" etc.
            match = re.match(r"^\d+[\.\)\:]?\s*(.+)$", line)
            if match:
                questions.append(match.group(1))
            elif line and not line[0].isdigit():
                # If line doesn't start with number but looks like a question
                if "?" in line:
                    questions.append(line)

    # If parsing failed, try to split on question marks
    if len(questions) < num_questions // 2:
        questions = []
        parts = response_text.split("?")
        for part in parts[:-1]:  # Skip last empty part
            part = part.strip()
            # Remove leading numbers
            part = re.sub(r"^\d+[\.\)\:]?\s*", "", part)
            if part:
                questions.append(part + "?")

    return questions[:num_questions]


def process_document(path: Path) -> ResearchMaterial | None:
    """Process a local document (PDF, text, etc.) into research material.

    Args:
        path: Path to the document

    Returns:
        ResearchMaterial if successfully processed, None otherwise
    """
    try:
        content = read_document(path)
        return ResearchMaterial(
            source=str(path),
            content=content,
            source_type="document",
        )
    except Exception:
        return None


def process_url(url: str) -> ResearchMaterial | None:
    """Fetch and process a URL into research material.

    Args:
        url: URL to fetch and process

    Returns:
        ResearchMaterial if successfully processed, None otherwise
    """
    try:
        content = fetch_url(url)
        return ResearchMaterial(
            source=url,
            content=content,
            source_type="url",
        )
    except Exception:
        return None


def ingest_research(
    topic: str,
    docs: list[str],
    urls: list[str],
) -> tuple[str, list[str]]:
    """Process all research materials and generate questions.

    Args:
        topic: Interview topic.
        docs: List of document paths.
        urls: List of URLs.

    Returns:
        Tuple of (aggregated_content, questions).
    """
    # Aggregate all research content
    aggregated = aggregate_research(docs, urls)

    # Generate questions
    questions = generate_questions(topic, aggregated)

    return aggregated, questions
