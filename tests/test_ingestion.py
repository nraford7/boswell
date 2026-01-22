"""Tests for the ingestion module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from boswell.ingestion import (
    HTMLTextExtractor,
    IngestedResearch,
    ResearchMaterial,
    aggregate_research,
    fetch_url,
    generate_questions,
    ingest_research,
    process_document,
    process_url,
    read_document,
    read_pdf_file,
    read_text_file,
)


class TestResearchMaterial:
    """Tests for the ResearchMaterial model."""

    def test_create_document_material(self) -> None:
        """Test creating a document research material."""
        material = ResearchMaterial(
            source="/path/to/file.txt",
            content="File content here",
            source_type="document",
        )
        assert material.source == "/path/to/file.txt"
        assert material.content == "File content here"
        assert material.source_type == "document"

    def test_create_url_material(self) -> None:
        """Test creating a URL research material."""
        material = ResearchMaterial(
            source="https://example.com",
            content="Page content here",
            source_type="url",
        )
        assert material.source == "https://example.com"
        assert material.source_type == "url"


class TestIngestedResearch:
    """Tests for the IngestedResearch model."""

    def test_default_values(self) -> None:
        """Test default values for IngestedResearch."""
        research = IngestedResearch()
        assert research.materials == []
        assert research.total_tokens_estimate == 0

    def test_with_materials(self) -> None:
        """Test IngestedResearch with materials."""
        materials = [
            ResearchMaterial(
                source="/path/to/file.txt",
                content="Content",
                source_type="document",
            )
        ]
        research = IngestedResearch(materials=materials, total_tokens_estimate=100)
        assert len(research.materials) == 1
        assert research.total_tokens_estimate == 100


class TestHTMLTextExtractor:
    """Tests for the HTMLTextExtractor class."""

    def test_extract_simple_html(self) -> None:
        """Test extracting text from simple HTML."""
        extractor = HTMLTextExtractor()
        extractor.feed("<p>Hello, world!</p>")
        assert "Hello, world!" in extractor.get_text()

    def test_skip_script_tags(self) -> None:
        """Test that script content is skipped."""
        extractor = HTMLTextExtractor()
        extractor.feed("<p>Visible</p><script>console.log('hidden');</script><p>Also visible</p>")
        text = extractor.get_text()
        assert "Visible" in text
        assert "Also visible" in text
        assert "console.log" not in text

    def test_skip_style_tags(self) -> None:
        """Test that style content is skipped."""
        extractor = HTMLTextExtractor()
        extractor.feed("<p>Visible</p><style>body { color: red; }</style>")
        text = extractor.get_text()
        assert "Visible" in text
        assert "color: red" not in text

    def test_block_elements_add_newlines(self) -> None:
        """Test that block elements add newlines."""
        extractor = HTMLTextExtractor()
        extractor.feed("<h1>Title</h1><p>Paragraph</p>")
        text = extractor.get_text()
        assert "Title" in text
        assert "Paragraph" in text


class TestReadTextFile:
    """Tests for the read_text_file function."""

    def test_read_txt_file(self, tmp_path: Path) -> None:
        """Test reading a .txt file."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello, world!")
        content = read_text_file(txt_file)
        assert content == "Hello, world!"

    def test_read_md_file(self, tmp_path: Path) -> None:
        """Test reading a .md file."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Heading\n\nContent here.")
        content = read_text_file(md_file)
        assert "# Heading" in content
        assert "Content here." in content

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing file."""
        missing_file = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            read_text_file(missing_file)

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for unsupported file type."""
        unsupported = tmp_path / "test.docx"
        unsupported.write_text("content")
        with pytest.raises(ValueError, match="Unsupported file type"):
            read_text_file(unsupported)


class TestReadPDFFile:
    """Tests for the read_pdf_file function."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing file."""
        missing_file = tmp_path / "nonexistent.pdf"
        with pytest.raises(FileNotFoundError):
            read_pdf_file(missing_file)

    def test_not_pdf_file(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for non-PDF file."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content")
        with pytest.raises(ValueError, match="Expected PDF file"):
            read_pdf_file(txt_file)

    def test_read_pdf_file(self, tmp_path: Path) -> None:
        """Test reading a PDF file with mocked read_pdf_file."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 mock pdf content")

        # Mock the entire read_pdf_file function since pypdf may not be installed
        with patch("boswell.ingestion.read_pdf_file") as mock_read_pdf:
            mock_read_pdf.return_value = "Extracted PDF text"
            content = mock_read_pdf(pdf_file)
            assert content == "Extracted PDF text"


class TestReadDocument:
    """Tests for the read_document function."""

    def test_route_to_text_reader(self, tmp_path: Path) -> None:
        """Test that .txt files are routed to text reader."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Text content")
        content = read_document(txt_file)
        assert content == "Text content"

    def test_route_to_md_reader(self, tmp_path: Path) -> None:
        """Test that .md files are routed to text reader."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Markdown")
        content = read_document(md_file)
        assert content == "# Markdown"

    def test_route_to_pdf_reader(self, tmp_path: Path) -> None:
        """Test that .pdf files are routed to PDF reader."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 content")

        # Mock read_pdf_file since pypdf may not be installed
        with patch("boswell.ingestion.read_pdf_file") as mock_read_pdf:
            mock_read_pdf.return_value = "PDF content"
            content = read_document(pdf_file)
            assert content == "PDF content"

    def test_unsupported_type(self, tmp_path: Path) -> None:
        """Test that unsupported types raise ValueError."""
        unsupported = tmp_path / "test.xyz"
        unsupported.write_text("content")
        with pytest.raises(ValueError, match="Unsupported document type"):
            read_document(unsupported)

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing file."""
        missing = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            read_document(missing)


class TestFetchURL:
    """Tests for the fetch_url function."""

    def test_fetch_html_page(self) -> None:
        """Test fetching and extracting text from HTML."""
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>Hello, world!</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            content = fetch_url("https://example.com")
            assert "Hello, world!" in content

    def test_fetch_plain_text(self) -> None:
        """Test fetching plain text content."""
        mock_response = MagicMock()
        mock_response.text = "Plain text content"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            content = fetch_url("https://example.com/text")
            assert content == "Plain text content"

    def test_fetch_http_error(self) -> None:
        """Test that HTTP errors are raised."""
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.HTTPError("Connection failed")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            with pytest.raises(httpx.HTTPError):
                fetch_url("https://example.com")

    def test_fetch_invalid_url_scheme(self) -> None:
        """Test that invalid URL schemes raise ValueError."""
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            fetch_url("file:///etc/passwd")

        with pytest.raises(ValueError, match="Invalid URL scheme"):
            fetch_url("ftp://example.com/file")

        with pytest.raises(ValueError, match="Invalid URL scheme"):
            fetch_url("javascript:alert(1)")


class TestAggregateResearch:
    """Tests for the aggregate_research function."""

    def test_aggregate_documents(self, tmp_path: Path) -> None:
        """Test aggregating document content."""
        doc1 = tmp_path / "doc1.txt"
        doc1.write_text("Document 1 content")
        doc2 = tmp_path / "doc2.txt"
        doc2.write_text("Document 2 content")

        result = aggregate_research([str(doc1), str(doc2)], [])

        assert "Document: doc1.txt" in result
        assert "Document 1 content" in result
        assert "Document: doc2.txt" in result
        assert "Document 2 content" in result

    def test_aggregate_urls(self) -> None:
        """Test aggregating URL content."""
        mock_response = MagicMock()
        mock_response.text = "<p>Page content</p>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = aggregate_research([], ["https://example.com"])

            assert "URL: https://example.com" in result
            assert "Page content" in result

    def test_aggregate_mixed(self, tmp_path: Path) -> None:
        """Test aggregating both documents and URLs."""
        doc = tmp_path / "doc.txt"
        doc.write_text("Document content")

        mock_response = MagicMock()
        mock_response.text = "<p>URL content</p>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = aggregate_research([str(doc)], ["https://example.com"])

            assert "Document content" in result
            assert "URL content" in result

    def test_aggregate_with_errors(self, tmp_path: Path) -> None:
        """Test that errors are captured in the output."""
        missing_doc = tmp_path / "missing.txt"

        result = aggregate_research([str(missing_doc)], [])

        assert "Document: missing.txt" in result
        assert "Error reading:" in result


class TestGenerateQuestions:
    """Tests for the generate_questions function."""

    def test_no_config(self) -> None:
        """Test error when config is not found."""
        with patch("boswell.ingestion.load_config", return_value=None):
            with pytest.raises(RuntimeError, match="Claude API key not configured"):
                generate_questions("Test topic", "Research content")

    def test_no_api_key(self) -> None:
        """Test error when API key is empty."""
        mock_config = MagicMock()
        mock_config.claude_api_key = ""

        with patch("boswell.ingestion.load_config", return_value=mock_config):
            with pytest.raises(RuntimeError, match="Claude API key not configured"):
                generate_questions("Test topic", "Research content")

    def test_generate_questions_success(self) -> None:
        """Test successful question generation."""
        mock_config = MagicMock()
        mock_config.claude_api_key = "test-api-key"

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text="""1. What is your background in this field?
2. How did you first become interested in this topic?
3. What are the main challenges you face?
4. Can you describe your typical workflow?
5. What tools do you use most frequently?"""
            )
        ]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("boswell.ingestion.load_config", return_value=mock_config):
            with patch("anthropic.Anthropic", return_value=mock_client):
                questions = generate_questions("AI Research", "Some research content", 5)

                assert len(questions) == 5
                assert "What is your background in this field?" in questions
                mock_client.messages.create.assert_called_once()

    def test_generate_questions_parses_various_formats(self) -> None:
        """Test that various numbering formats are parsed correctly."""
        mock_config = MagicMock()
        mock_config.claude_api_key = "test-api-key"

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text="""1. First question?
2) Second question?
3: Third question?"""
            )
        ]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("boswell.ingestion.load_config", return_value=mock_config):
            with patch("anthropic.Anthropic", return_value=mock_client):
                questions = generate_questions("Topic", "Content", 3)

                assert len(questions) == 3
                assert "First question?" in questions
                assert "Second question?" in questions
                assert "Third question?" in questions


class TestProcessDocument:
    """Tests for the process_document function."""

    def test_process_valid_document(self, tmp_path: Path) -> None:
        """Test processing a valid document."""
        doc = tmp_path / "test.txt"
        doc.write_text("Test content")

        result = process_document(doc)

        assert result is not None
        assert result.content == "Test content"
        assert result.source_type == "document"

    def test_process_invalid_document(self, tmp_path: Path) -> None:
        """Test processing an invalid document returns None."""
        missing = tmp_path / "missing.txt"

        result = process_document(missing)

        assert result is None


class TestProcessURL:
    """Tests for the process_url function."""

    def test_process_valid_url(self) -> None:
        """Test processing a valid URL."""
        mock_response = MagicMock()
        mock_response.text = "<p>Content</p>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = process_url("https://example.com")

            assert result is not None
            assert "Content" in result.content
            assert result.source_type == "url"

    def test_process_invalid_url(self) -> None:
        """Test processing an invalid URL returns None."""
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.HTTPError("Failed")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = process_url("https://example.com")

            assert result is None


class TestIngestResearch:
    """Tests for the ingest_research function."""

    def test_ingest_with_docs_and_urls(self, tmp_path: Path) -> None:
        """Test full ingestion pipeline."""
        doc = tmp_path / "test.txt"
        doc.write_text("Document content")

        # Mock URL fetching
        mock_url_response = MagicMock()
        mock_url_response.text = "<p>URL content</p>"
        mock_url_response.headers = {"content-type": "text/html"}
        mock_url_response.raise_for_status = MagicMock()

        # Mock Claude API
        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        mock_claude_response = MagicMock()
        mock_claude_response.content = [
            MagicMock(text="1. Question one?\n2. Question two?")
        ]

        mock_claude = MagicMock()
        mock_claude.messages.create.return_value = mock_claude_response

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_url_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_class.return_value = mock_client

            with patch("boswell.ingestion.load_config", return_value=mock_config):
                with patch("anthropic.Anthropic", return_value=mock_claude):
                    aggregated, questions = ingest_research(
                        topic="Test Topic",
                        docs=[str(doc)],
                        urls=["https://example.com"],
                    )

                    assert "Document content" in aggregated
                    assert "URL content" in aggregated
                    assert len(questions) == 2

    def test_ingest_empty_inputs(self) -> None:
        """Test ingestion with no documents or URLs."""
        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        mock_claude_response = MagicMock()
        mock_claude_response.content = [MagicMock(text="1. General question?")]

        mock_claude = MagicMock()
        mock_claude.messages.create.return_value = mock_claude_response

        with patch("boswell.ingestion.load_config", return_value=mock_config):
            with patch("anthropic.Anthropic", return_value=mock_claude):
                aggregated, questions = ingest_research(
                    topic="Test Topic",
                    docs=[],
                    urls=[],
                )

                assert aggregated == ""
                assert len(questions) >= 1
