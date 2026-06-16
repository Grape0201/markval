from typing import Literal

from pydantic import BaseModel, Field



class Paragraph(BaseModel):
    box: list[int]
    contents: str
    direction: Literal["horizontal", "vertical"]
    order: int
    role: str | None = None


class TableRow(BaseModel):
    box: list[int]
    score: float


class TableCol(BaseModel):
    box: list[int]
    score: float


class TableCell(BaseModel):
    col: int
    row: int
    col_span: int
    row_span: int
    box: list[int]
    contents: str


class Table(BaseModel):
    box: list[int]
    n_row: int
    n_col: int
    rows: list[TableRow]
    cols: list[TableCol]
    spans: list[dict]
    cells: list[TableCell]
    order: int


class Word(BaseModel):
    points: list[list[int]]
    content: str
    direction: Literal["horizontal", "vertical"]
    rec_score: float
    det_score: float


class Figure(BaseModel):
    pass


class Page(BaseModel):
    paragraphs: list[Paragraph] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)



if __name__ == "__main__":
    import json
    for doc in ["a.json", "b.json"]:
        with open(f"../poc_data/{doc}") as f:
            pages = json.load(f)
        for page in pages:
            Page.model_validate(page)
