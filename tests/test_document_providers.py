import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.document_providers import YomitokuProvider
from app.services.yomitoku_models import Page


@pytest.mark.anyio
async def test_yomitoku_provider_ocr_pdf(tmp_path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"dummy pdf contents")

    provider = YomitokuProvider(api_url="http://mock-ocr-api")

    # Mock response data representing parsed Page
    mock_response_data = [
        {
            "paragraphs": [
                {
                    "box": [0, 0, 100, 50],
                    "contents": "Test paragraph text",
                    "direction": "horizontal",
                    "order": 1,
                    "role": "text"
                }
            ],
            "tables": [],
            "words": [],
            "figures": []
        }
    ]

    # Mock httpx.AsyncClient.post response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        # Execute OCR
        raw_result = await provider.ocr_pdf(pdf_path)

        # Verify raw result matches
        assert raw_result == mock_response_data

        # Verify call arguments
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://mock-ocr-api/ocr"
        assert "files" in kwargs

    # Verify cached pages are parsed into Pydantic models correctly
    cached_pages = provider.get_ocr_pages()
    assert len(cached_pages) == 1
    assert isinstance(cached_pages[0], Page)
    assert len(cached_pages[0].paragraphs) == 1
    assert cached_pages[0].paragraphs[0].contents == "Test paragraph text"
