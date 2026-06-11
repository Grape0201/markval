#!/bin/bash
set -e

# Change directory to project root if script is run from elsewhere
cd "$(dirname "$0")/.."

echo "=== Starting PDF Matcher PoC-1 Pipeline ==="

echo "=== Step 1: Extract PDF to Markdown ==="
uv run python poc-1/step1_extract_markdown.py

echo "=== Step 2: Extract structured data using LLM ==="
uv run python poc-1/step2_structured_llm.py

echo "=== Step 3: Match File A items against File B references ==="
uv run python poc-1/step3_match_items.py

echo "=== Step 4: Export match report to CSV ==="
uv run python poc-1/step4_export_csv.py

echo "=== Pipeline Completed successfully! ==="
echo "Output files are stored in the 'poc_data' directory:"
echo " - Markdown extracted JSON: poc_data/poc1_extracted_a.json, poc_data/poc1_extracted_b.json"
echo " - Structured JSON: poc_data/poc1_structured_a.json, poc_data/poc1_structured_b.json"
echo " - Match results JSON: poc_data/poc1_matched_results.json"
echo " - CSV Report: poc_data/poc1_report.csv"
