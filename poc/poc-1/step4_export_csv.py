import csv
import json
from pathlib import Path

def main() -> None:
    workspace_dir = Path(__file__).resolve().parents[2]
    poc_data_dir = workspace_dir / "poc" / "poc_data"
    
    # Load step 3 matched results
    with open(poc_data_dir / "poc1_matched_results.json", "r", encoding="utf-8") as f:
        matched_data = json.load(f)
        
    csv_file = poc_data_dir / "poc1_report.csv"
    
    headers = [
        "Check Item Label",
        "Calculated Value",
        "Calculated Unit",
        "Calculated Page",
        "Status",
        "Source Document Label",
        "Source Value",
        "Source Unit",
        "Source Page",
        "Confidence",
        "AI Reasoning"
    ]
    
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        for result in matched_data["results"]:
            status = "Approved" if result["matched"] else "Mismatch"
            writer.writerow([
                result["check_item_label"],
                result["check_item_value"],
                result["check_item_unit"],
                result["check_item_page"],
                status,
                result.get("matched_source_label") or "",
                result.get("matched_source_value") or "",
                result.get("matched_source_unit") or "",
                result.get("matched_source_page") or "",
                result["confidence"],
                result["ai_reasoning"]
            ])
            
    print(f"Saved report to {csv_file}")

if __name__ == "__main__":
    main()
