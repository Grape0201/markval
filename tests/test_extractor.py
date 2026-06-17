import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.runnables import RunnableLambda

from app.services.yomitoku_models import Page, Paragraph, Word
from app.services.extractor import (
    extract_source_items_from_pdf,
    extract_check_items_from_pdf,
    PageSourceList,
    PageSourceItem,
    PageChecklist,
    PageCheckItem,
)


@pytest.mark.anyio
async def test_extract_source_items_with_mock_llm():
    # 1. LLM の Mock を作成
    mock_llm = MagicMock()
    
    fake_response = PageSourceList(
        items=[
            PageSourceItem(
                label="テスト荷重B",
                value_type="numeric",
                numeric_value=1200.0,
                unit="N/m²",
                context_text="屋根の固定荷重は1200.0N/m²とする。",
                source_block_ids=["B001"],
                category="固定荷重"
            )
        ]
    )
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda x: fake_response)

    # 2. PDFプロバイダーのモック
    mock_pages = [
        Page(
            paragraphs=[
                Paragraph(
                    box=[0, 0, 100, 50],
                    contents="屋根の固定荷重は1200.0N/m²とする。",
                    direction="horizontal",
                    order=1
                )
            ],
            words=[
                Word(
                    points=[[10, 10], [90, 10], [90, 40], [10, 40]],
                    content="1200.0",
                    direction="horizontal",
                    rec_score=0.99,
                    det_score=0.99
                )
            ]
        )
    ]
    
    with patch("app.services.extractor._get_ocr_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.ocr_pdf = AsyncMock()
        mock_provider.get_ocr_pages = MagicMock(return_value=mock_pages)
        mock_get_provider.return_value = mock_provider

        # 3. テスト対象の関数を実行
        result = await extract_source_items_from_pdf(
            pdf_path=Path("dummy_b.pdf"),
            llm=mock_llm
        )

    # 4. 検証
    assert len(result) == 1
    assert result[0]["label"] == "テスト荷重B"
    assert result[0]["value"] == 1200.0
    assert result[0]["bbox"] is not None
    assert "x0" in result[0]["bbox"]


@pytest.mark.anyio
async def test_extract_check_items_with_mock_llm():
    # 1. LLM の Mock を作成
    mock_llm = MagicMock()
    
    fake_response = PageChecklist(
        items=[
            PageCheckItem(
                label="テスト荷重A",
                value_type="numeric",
                numeric_value=1500.0,
                unit="N/m²",
                context="床の固定荷重 1500.0 N/m²",
                source_hint="表1",
                source_block_ids=["B001"],
                category="固定荷重"
            )
        ]
    )
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda x: fake_response)

    # 2. PDFプロバイダーのモック
    mock_pages = [
        Page(
            paragraphs=[
                Paragraph(
                    box=[0, 0, 100, 50],
                    contents="床の固定荷重 1500.0 N/m²",
                    direction="horizontal",
                    order=1
                )
            ],
            words=[
                Word(
                    points=[[10, 10], [90, 10], [90, 40], [10, 40]],
                    content="1500.0",
                    direction="horizontal",
                    rec_score=0.99,
                    det_score=0.99
                )
            ]
        )
    ]
    
    with patch("app.services.extractor._get_ocr_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.ocr_pdf = AsyncMock()
        mock_provider.get_ocr_pages = MagicMock(return_value=mock_pages)
        mock_get_provider.return_value = mock_provider

        # 3. テスト対象の関数を実行
        result = await extract_check_items_from_pdf(
            pdf_path=Path("dummy_a.pdf"),
            llm=mock_llm
        )

    # 4. 検証
    assert len(result) == 1
    assert result[0]["label"] == "テスト荷重A"
    assert result[0]["value"] == 1500.0
    assert result[0]["bbox"] is not None
    assert "x0" in result[0]["bbox"]
