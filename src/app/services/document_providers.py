"""OCR プロバイダー抽象基盤 + Yomitoku 実装.

将来的に Azure Document Intelligence 等の他 OCR API にも対応できるよう
抽象クラス ``OCRProvider`` を定義し、各プロバイダーはこれを継承する。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from app.core.semaphores import get_yomitoku_semaphore
from app.services.yomitoku_models import Page


def _clean_and_parse_value(text: str) -> float | None:
    candidate = text.strip()

    if not re.match(r"^-?[0-9,]+(\.[0-9]+)?$", candidate):
        return None
    cleaned = candidate.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


class OCRProvider(ABC):
    """OCR プロバイダーの抽象基底クラス.

    各実装は以下を提供する:
    - ``ocr_pdf``: PDF → OCR ページデータ（プロバイダー固有のフォーマット）
    - ``get_ocr_pages``: OCR 結果を Yomitoku Page モデルに変換
    """

    @abstractmethod
    async def ocr_pdf(self, pdf_path: Path) -> list[dict[str, Any]]:
        """PDF を OCR にかけ、ページごとの生データを返す."""
        raise NotImplementedError

    @abstractmethod
    def get_ocr_pages(self) -> list[Page]:
        """直前の OCR 結果を Yomitoku Page モデルのリストとして返す.

        ``ocr_pdf`` の呼び出し後にのみ有効。
        """
        raise NotImplementedError


class YomitokuProvider(OCRProvider):
    """Yomitoku OCR API プロバイダー."""

    def __init__(self, api_url: str | None = None) -> None:
        import os

        self._api_url = api_url or os.environ.get(
            "YOMITOKU_API_URL", "http://localhost:8080"
        )
        self._cached_pages: list[Page] = []

    async def ocr_pdf(self, pdf_path: Path) -> list[dict[str, Any]]:
        """Yomitoku API に PDF を送信し、OCR 結果を取得する."""
        import asyncio

        semaphore = get_yomitoku_semaphore()
        async with semaphore:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # 1. Upload
                with pdf_path.open("rb") as f:
                    files = {"file": (pdf_path.name, f, "application/pdf")}
                    response = await client.post(
                        f"{self._api_url}/ocr/upload",
                        files=files,
                    )
                response.raise_for_status()
                task_id = response.json().get("task_id")
                if not task_id:
                    raise RuntimeError(
                        "Failed to obtain task_id from Yomitoku upload endpoint"
                    )

                # 2. Poll status (SUCCESS / FAILURE)
                # Max 300 seconds timeout
                status = "PENDING"
                for _ in range(300):
                    status_response = await client.get(
                        f"{self._api_url}/ocr/status/{task_id}"
                    )
                    status_response.raise_for_status()
                    status_data = status_response.json()
                    status = status_data.get("status")

                    if status == "SUCCESS":
                        break
                    elif status == "FAILURE":
                        error_detail = status_data.get("error", "Unknown error")
                        raise RuntimeError(f"Yomitoku OCR task failed: {error_detail}")

                    await asyncio.sleep(1.0)
                else:
                    raise TimeoutError(
                        f"Yomitoku OCR task timed out for task_id: {task_id}"
                    )

                # 3. Retrieve final result
                result_response = await client.get(
                    f"{self._api_url}/ocr/result/{task_id}",
                    params={"format": "json"},
                )
                result_response.raise_for_status()
                raw_pages: list[dict[str, Any]] = result_response.json()

        # パースしてキャッシュ
        self._cached_pages = [Page.model_validate(p) for p in raw_pages]
        return raw_pages

    def get_ocr_pages(self) -> list[Page]:
        """キャッシュ済みの OCR ページを返す."""
        return self._cached_pages
