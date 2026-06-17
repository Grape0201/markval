import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Yomitoku Mock Server",
    description="A simplified mock server of Yomitoku AI OCR Server for testing YomitokuProvider",
    version="1.0.0",
)

# InMemory task storage to associate task_id with uploaded filename.
# PEP 585: Do not use typing.Dict or typing.List, use built-in dict or list.
_tasks: dict[str, str] = {}


@app.post("/ocr/upload", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    text_detector: str = Form("dbnetv2_1"),
    text_recognizer: str = Form("parseq-large-v4_1"),
    layout_parser: str = Form("rtdetrv2v2"),
) -> dict[str, str]:
    """
    Simulates document upload and returns a generated task ID.
    Associates the task ID with the filename to decide which JSON to return later.
    """
    task_id = str(uuid.uuid4())
    filename = file.filename or ""
    _tasks[task_id] = filename
    return {"task_id": task_id}


@app.get("/ocr/status/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """
    Simulates task status query. Always returns SUCCESS for simplicity.
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {
        "task_id": task_id,
        "status": "SUCCESS",
        "progress": {
            "current": 1,
            "total": 1,
        },
    }


@app.get("/ocr/result/{task_id}")
async def get_task_result(
    task_id: str,
    format: str = Query("json"),
) -> Any:
    """
    Retrieves the OCR results from local mock data based on the original file name.
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if format.lower() != "json":
        raise HTTPException(
            status_code=400,
            detail=f"Only 'json' format is supported in this mock. Got '{format}'",
        )

    filename = _tasks[task_id]

    # Path manipulation must use pathlib.Path and NOT os.path
    base_dir = Path(__file__).resolve().parent
    poc_data_dir = base_dir.parent / "poc" / "poc_data"

    if "b" in filename.lower():
        json_file = poc_data_dir / "b.json"
    else:
        json_file = poc_data_dir / "a.json"

    if not json_file.exists():
        raise HTTPException(
            status_code=404, detail=f"Mock data file not found: {json_file}"
        )

    try:
        with json_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read mock data: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
