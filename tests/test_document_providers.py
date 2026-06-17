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
                    "role": "text",
                }
            ],
            "tables": [],
            "words": [],
            "figures": [],
        }
    ]

    # Mock HTTP responses for upload, status, and result endpoints
    mock_upload_response = MagicMock()
    mock_upload_response.status_code = 202
    mock_upload_response.json.return_value = {"task_id": "test-task-id"}
    mock_upload_response.raise_for_status = MagicMock()

    mock_status_response = MagicMock()
    mock_status_response.status_code = 200
    mock_status_response.json.return_value = {
        "task_id": "test-task-id",
        "status": "SUCCESS",
    }
    mock_status_response.raise_for_status = MagicMock()

    mock_result_response = MagicMock()
    mock_result_response.status_code = 200
    mock_result_response.json.return_value = mock_response_data
    mock_result_response.raise_for_status = MagicMock()

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        mock_post.return_value = mock_upload_response
        mock_get.side_effect = [mock_status_response, mock_result_response]

        # Execute OCR
        raw_result = await provider.ocr_pdf(pdf_path)

        # Verify raw result matches
        assert raw_result == mock_response_data

        # Verify POST call (upload)
        mock_post.assert_called_once()
        post_args, post_kwargs = mock_post.call_args
        assert post_args[0] == "http://mock-ocr-api/ocr/upload"
        assert "files" in post_kwargs

        # Verify GET calls (status and result)
        assert mock_get.call_count == 2

        get_calls = mock_get.call_args_list
        # First GET call: status check
        assert get_calls[0][0][0] == "http://mock-ocr-api/ocr/status/test-task-id"
        # Second GET call: result retrieval
        assert get_calls[1][0][0] == "http://mock-ocr-api/ocr/result/test-task-id"
        assert get_calls[1][1].get("params") == {"format": "json"}

    # Verify cached pages are parsed into Pydantic models correctly
    cached_pages = provider.get_ocr_pages()
    assert len(cached_pages) == 1
    assert isinstance(cached_pages[0], Page)
    assert len(cached_pages[0].paragraphs) == 1
    assert cached_pages[0].paragraphs[0].contents == "Test paragraph text"
