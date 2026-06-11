#!/bin/bash
set -e

# Change directory to project root if script is run from elsewhere
cd "$(dirname "$0")/.."

echo "=== Starting PDF Matcher PoC-2 Pipeline ==="

echo "=== Step 1: Extract and Map Bboxes (File A & File B) ==="
uv run python poc-2/step1_extract_bboxes.py

echo "=== Step 2: Annotate PDFs (File A & File B) ==="
uv run python poc-2/step2_annotate_pdf.py

echo "=== PoC-2 Pipeline Completed Successfully! ==="
echo "Output files are stored in the 'poc_data' directory:"
echo " - File A Bbox JSON: poc_data/poc2_structured_a_with_bboxes.json"
echo " - File B Bbox JSON: poc_data/poc2_structured_b_with_bboxes.json"
echo " - Annotated File A PDF: poc_data/poc2_annotated_file_a.pdf"
echo " - Annotated File B PDF: poc_data/poc2_annotated_file_b.pdf"
