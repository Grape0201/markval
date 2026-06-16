#!/bin/bash
# PoC-3: ブロック ID 参照方式によるPDF抽出と座標特定
#
# 使い方:
#   # Step 1 のみ実行（LLM 不要）
#   bash run_all.sh --step1
#
#   # Step 2: プロンプト生成のみ（--dry-run）
#   bash run_all.sh --step2-dry
#
#   # Step 2: 手動保存した LLM レスポンスを読み込み
#   bash run_all.sh --step2-load
#
#   # Step 3 + Step 4（Bbox 解決 + レポート）
#   bash run_all.sh --step3-4
#
#   # 全ステップ実行（LLM API キーが必要）
#   bash run_all.sh --all

set -euo pipefail
cd "$(dirname "$0")"

run_step1() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 1: Build blocks from Yomitoku JSON"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    uv run python step1_build_blocks.py
}

run_step2_dry() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 2: Generate prompts (dry run)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    uv run python step2_extract_with_ids.py --dry-run
}

run_step2_load() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 2: Load manual LLM responses"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    uv run python step2_extract_with_ids.py --load-responses
}

run_step2_llm() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 2: LLM extraction (API key required)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    uv run python step2_extract_with_ids.py
}

run_step3() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 3: Resolve block IDs to bboxes"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    uv run python step3_resolve_bbox.py
}

run_step4() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 4: Generate report"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    uv run python step4_report.py
}

case "${1:---help}" in
    --step1)
        run_step1
        ;;
    --step2-dry)
        run_step2_dry
        ;;
    --step2-load)
        run_step2_load
        ;;
    --step2-llm)
        run_step2_llm
        ;;
    --step3-4)
        run_step3
        run_step4
        ;;
    --all)
        run_step1
        run_step2_llm
        run_step3
        run_step4
        ;;
    --help|-h)
        echo "Usage: bash run_all.sh [OPTION]"
        echo ""
        echo "Options:"
        echo "  --step1       Step 1 のみ（ブロック構築、LLM 不要）"
        echo "  --step2-dry   Step 2 プロンプト生成のみ"
        echo "  --step2-load  Step 2 手動 LLM レスポンス読み込み"
        echo "  --step2-llm   Step 2 LLM 呼び出し（API キー必要）"
        echo "  --step3-4     Step 3 + 4（Bbox 解決 + レポート）"
        echo "  --all         全ステップ実行"
        echo "  --help        このヘルプを表示"
        ;;
    *)
        echo "Unknown option: $1"
        echo "Run 'bash run_all.sh --help' for usage."
        exit 1
        ;;
esac
