import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.runnables import RunnableLambda
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
    
    # 期待される構造化データのモックレスポンスを返す RunnableLambda を設定
    fake_response = PageSourceList(
        items=[
            PageSourceItem(
                label="テスト荷重B",
                value=1200.0,
                unit="N/m²",
                context_text="屋根の固定荷重は1200N/m²とする。",
                category="固定荷重"
            )
        ]
    )
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda x: fake_response)

    # 2. PDFプロバイダーのモック
    mock_pages = [{"page": 1, "markdown": "ダミーのページテキストB"}]
    
    with patch("app.services.extractor._select_document_provider") as mock_select_provider:
        mock_provider = MagicMock()
        mock_provider.extract_markdown_pages = AsyncMock(return_value=mock_pages)
        mock_provider.annotate = lambda pdf, items: [{**item, "bbox": [0, 0, 100, 100]} for item in items]
        mock_select_provider.return_value = mock_provider

        # 3. テスト対象の関数を実行
        result = await extract_source_items_from_pdf(
            pdf_path=Path("dummy_b.pdf"),
            llm=mock_llm
        )

    # 4. 検証
    assert len(result) == 1
    assert result[0]["label"] == "テスト荷重B"
    assert result[0]["value"] == 1200.0
    assert result[0]["bbox"] == [0, 0, 100, 100]


@pytest.mark.anyio
async def test_extract_check_items_with_mock_llm():
    # 1. LLM の Mock を作成
    mock_llm = MagicMock()
    
    # 期待される構造化データのモックレスポンスを返す RunnableLambda を設定
    fake_response = PageChecklist(
        items=[
            PageCheckItem(
                label="テスト荷重A",
                symbol="G",
                value=1500.0,
                unit="N/m²",
                context="床の固定荷重 1500 N/m²",
                source_hint="表1",
                category="固定荷重"
            )
        ]
    )
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda x: fake_response)

    # 2. PDFプロバイダーのモック
    mock_pages = [{"page": 1, "markdown": "ダミーのページテキストA"}]
    
    with patch("app.services.extractor._select_document_provider") as mock_select_provider:
        mock_provider = MagicMock()
        mock_provider.extract_markdown_pages = AsyncMock(return_value=mock_pages)
        mock_provider.annotate = lambda pdf, items: [{**item, "bbox": [0, 0, 100, 100]} for item in items]
        mock_select_provider.return_value = mock_provider

        # 3. テスト対象の関数を実行
        result = await extract_check_items_from_pdf(
            pdf_path=Path("dummy_a.pdf"),
            llm=mock_llm
        )

    # 4. 検証
    assert len(result) == 1
    assert result[0]["label"] == "テスト荷重A"
    assert result[0]["value"] == 1500.0
    assert result[0]["bbox"] == [0, 0, 100, 100]
