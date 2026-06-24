"""Step 4: Bbox 解決済みの結果から CSV レポートと検証サマリーを出力する."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _format_bbox(bbox: list[int] | None) -> str:
    """Bbox を人間が読みやすい文字列にする."""
    if bbox is None:
        return "—"
    return f"[{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]"


def _get_value_display(item: dict[str, Any]) -> str:
    """値の表示文字列を生成する."""
    vt = item.get("value_type", "numeric")
    if vt == "numeric":
        v = item.get("numeric_value")
        unit = item.get("unit") or ""
        return f"{v} {unit}".strip() if v is not None else "—"
    elif vt == "name":
        return item.get("text_value") or "—"
    elif vt == "formula":
        return item.get("formula_value") or "—"
    return "—"


def generate_csv(data_dir: Path, file_type: str) -> None:
    """CSV レポートを生成する."""
    resolved_path = data_dir / f"poc3_resolved_{file_type}.json"
    if not resolved_path.exists():
        print(f"  ⏭  {resolved_path} not found (run step3 first)")
        return

    with resolved_path.open() as f:
        data = json.load(f)

    output_path = data_dir / f"poc3_report_{file_type}.csv"

    with output_path.open("w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "Page",
                "Label",
                "Value",
                "Category",
                "Block IDs",
                "Block ID Valid",
                "Bbox (Coarse)",
                "Bbox (Refined)",
                "Bbox (Final)",
                "Context",
            ]
        )

        for page_data in data.get("pages", []):
            page_num = page_data["page"]
            for item in page_data["items"]:
                writer.writerow(
                    [
                        page_num,
                        item.get("label", ""),
                        _get_value_display(item),
                        item.get("category", ""),
                        ", ".join(item.get("source_block_ids", [])),
                        "✓" if item.get("block_id_valid") else "✗",
                        _format_bbox(item.get("bbox_coarse")),
                        _format_bbox(item.get("bbox_refined")),
                        _format_bbox(item.get("bbox")),
                        item.get("context", "")[:80],
                    ]
                )

    print(f"  ✅ CSV saved to {output_path}")


def generate_summary(data_dir: Path) -> None:
    """全ファイルの検証サマリーを出力する."""
    print("\n" + "=" * 60)
    print("📊 PoC-3 検証サマリー")
    print("=" * 60)

    for ft in ["a", "b"]:
        resolved_path = data_dir / f"poc3_resolved_{ft}.json"
        if not resolved_path.exists():
            continue

        with resolved_path.open() as f:
            data = json.load(f)

        summary = data.get("summary", {})
        print(f"\n--- File {ft.upper()} ({data.get('source', '')}) ---")
        print(f"  抽出アイテム数:    {summary.get('total_items', 0)}")
        print(f"  有効ブロック ID:   {summary.get('valid_block_ids', 0)} "
              f"({summary.get('block_id_accuracy', 0):.1%})")
        print(f"  精密 Bbox 成功:    {summary.get('refined_bbox', 0)} "
              f"({summary.get('refinement_rate', 0):.1%})")

        # ハルシネーション（無効 ID）の詳細
        hallucinated = []
        for page_data in data.get("pages", []):
            for item in page_data["items"]:
                if item.get("invalid_block_ids"):
                    hallucinated.append(
                        {
                            "page": page_data["page"],
                            "label": item["label"],
                            "invalid_ids": item["invalid_block_ids"],
                        }
                    )

        if hallucinated:
            print(f"\n  ⚠️  ハルシネーション（存在しない ID）: {len(hallucinated)} 件")
            for h in hallucinated:
                print(f"     Page {h['page']}: '{h['label']}' → {h['invalid_ids']}")
        else:
            print("\n  ✅ ハルシネーションなし")

        # Bbox 解決できなかったアイテム
        no_bbox = []
        for page_data in data.get("pages", []):
            for item in page_data["items"]:
                if item.get("bbox") is None:
                    no_bbox.append(
                        {"page": page_data["page"], "label": item["label"]}
                    )

        if no_bbox:
            print(f"  ⚠️  Bbox 未解決: {len(no_bbox)} 件")
            for nb in no_bbox:
                print(f"     Page {nb['page']}: '{nb['label']}'")

    print("\n" + "=" * 60)


def main() -> None:
    data_dir = Path(__file__).resolve().parent.parent / "poc_data"

    for ft in ["a", "b"]:
        print(f"📄 Generating report for File {ft.upper()} ...")
        generate_csv(data_dir, ft)

    generate_summary(data_dir)


if __name__ == "__main__":
    main()
