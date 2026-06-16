"""Step 1: Yomitoku JSON → ブロック ID 付きテキスト + ID-Bbox 対応表を構築する."""

from __future__ import annotations

import json
from pathlib import Path

from load_yomitoku_json import Page, Paragraph, Table
from models import BlockInfo, DocumentBlocks, PageBlocks, WordInfo


def _points_to_box(points: list[list[int]]) -> list[int]:
    """4 隅ポリゴンを [x0, y0, x1, y1] に変換する."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _build_table_rows(
    table: Table, table_idx: int
) -> list[tuple[str, BlockInfo, str | None]]:
    """テーブルを行単位でブロック化する.

    Returns:
        (formatted_line, block_info, table_header_or_none) のリスト
    """
    # セルを行番号でグルーピング
    rows_dict: dict[int, list] = {}
    for cell in table.cells:
        rows_dict.setdefault(cell.row, []).append(cell)

    table_id = f"T{table_idx:03d}"
    header = f"【テーブル {table_id}】"
    result: list[tuple[str, BlockInfo, str | None]] = []

    for row_num in sorted(rows_dict):
        row_cells = sorted(rows_dict[row_num], key=lambda c: c.col)
        row_id = f"{table_id}-R{row_num}"

        # 行内セルの Bbox をマージ
        x0 = min(c.box[0] for c in row_cells)
        y0 = min(c.box[1] for c in row_cells)
        x1 = max(c.box[2] for c in row_cells)
        y1 = max(c.box[3] for c in row_cells)

        cell_texts = [c.contents for c in row_cells]
        formatted = f"[{row_id}] | {' | '.join(cell_texts)} |"

        block_info = BlockInfo(
            block_id=row_id,
            block_type="table_row",
            text=" | ".join(cell_texts),
            box=[x0, y0, x1, y1],
            cells=[
                {"contents": c.contents, "box": list(c.box)} for c in row_cells
            ],
        )

        # テーブルの最初の行にだけヘッダーを付与
        is_first = row_num == min(rows_dict)
        result.append((formatted, block_info, header if is_first else None))

    return result


def _build_page_blocks(page: Page, page_num: int) -> PageBlocks:
    """1 ページ分のブロック構造を構築する."""
    # 段落とテーブルを order でソートしてインターリーブ
    items: list[tuple[int, str, Paragraph | Table]] = []
    for para in page.paragraphs:
        items.append((para.order, "paragraph", para))
    for table in page.tables:
        items.append((table.order, "table", table))
    items.sort(key=lambda x: x[0])

    block_map: dict[str, BlockInfo] = {}
    lines: list[str] = []
    block_counter = 0
    table_counter = 0

    for _, item_type, data in items:
        if item_type == "paragraph":
            block_counter += 1
            bid = f"B{block_counter:03d}"
            assert isinstance(data, Paragraph)

            block_info = BlockInfo(
                block_id=bid,
                block_type="paragraph",
                text=data.contents,
                box=list(data.box),
            )
            block_map[bid] = block_info
            lines.append(f"[{bid}/paragraph] {data.contents}")

        elif item_type == "table":
            table_counter += 1
            assert isinstance(data, Table)
            table_rows = _build_table_rows(data, table_counter)

            for formatted, block_info, table_header in table_rows:
                block_map[block_info.block_id] = block_info
                if table_header:
                    lines.append("")
                    lines.append(table_header)
                lines.append(formatted)

    # Word を簡易フォーマットに変換（Phase 2 精密検索用）
    words: list[WordInfo] = []
    for w in page.words:
        box = _points_to_box(w.points)
        words.append(
            WordInfo(content=w.content, box=box, rec_score=w.rec_score)
        )

    return PageBlocks(
        page=page_num,
        formatted_text="\n".join(lines),
        block_map=block_map,
        words=words,
    )


def process_document(json_path: Path) -> DocumentBlocks:
    """Yomitoku JSON ファイルを読み込み、ブロック構造に変換する."""
    with json_path.open() as f:
        raw_pages = json.load(f)

    pages: list[PageBlocks] = []
    for i, raw_page in enumerate(raw_pages):
        page = Page.model_validate(raw_page)
        page_blocks = _build_page_blocks(page, page_num=i + 1)
        pages.append(page_blocks)

    return DocumentBlocks(source=json_path.name, pages=pages)


def main() -> None:
    data_dir = Path(__file__).resolve().parent.parent / "poc_data"

    for doc_name in ["a.json", "b.json"]:
        json_path = data_dir / doc_name
        if not json_path.exists():
            print(f"⏭  Skipping {doc_name}: file not found")
            continue

        print(f"📄 Processing {doc_name} ...")
        result = process_document(json_path)

        # ブロック構造を保存
        output_path = data_dir / f"poc3_blocks_{doc_name[0]}.json"
        with output_path.open("w") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

        # LLM 入力テキストも個別に保存（確認用）
        for page in result.pages:
            prompt_path = data_dir / f"poc3_prompt_{doc_name[0]}_p{page.page}.txt"
            with prompt_path.open("w") as f:
                f.write(page.formatted_text)

        # サマリー表示
        for page in result.pages:
            n_blocks = len(page.block_map)
            n_words = len(page.words)
            print(f"  Page {page.page}: {n_blocks} blocks, {n_words} words")
            preview = page.formatted_text.split("\n")[:8]
            for line in preview:
                if line.strip():
                    print(f"    {line}")
            total_lines = len(page.formatted_text.split("\n"))
            if total_lines > 8:
                print(f"    ... ({total_lines} lines total)")

        print(f"  ✅ Saved to {output_path}")
        print()


if __name__ == "__main__":
    main()
