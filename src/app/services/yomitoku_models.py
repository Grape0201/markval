"""Yomitoku OCR エンジンが出力する JSON の Pydantic モデル定義."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Paragraph(BaseModel):
    """段落（テキストブロック）."""

    box: list[int]
    contents: str
    direction: Literal["horizontal", "vertical"]
    order: int
    role: str | None = None


class TableRow(BaseModel):
    """テーブルの行."""

    box: list[int]
    score: float


class TableCol(BaseModel):
    """テーブルの列."""

    box: list[int]
    score: float


class TableCell(BaseModel):
    """テーブルのセル."""

    col: int
    row: int
    col_span: int
    row_span: int
    box: list[int]
    contents: str


class Table(BaseModel):
    """テーブル."""

    box: list[int]
    n_row: int
    n_col: int
    rows: list[TableRow]
    cols: list[TableCol]
    spans: list[dict]
    cells: list[TableCell]
    order: int


class Word(BaseModel):
    """単語（文字認識結果）."""

    points: list[list[int]]
    content: str
    direction: Literal["horizontal", "vertical"]
    rec_score: float
    det_score: float


class Figure(BaseModel):
    """図表領域（現時点では属性なし）."""


class Page(BaseModel):
    """1 ページ分の OCR 結果."""

    paragraphs: list[Paragraph] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
