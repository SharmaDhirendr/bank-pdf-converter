import os
from fastapi import FastAPI, UploadFile, Form, Header, HTTPException
from fastapi.responses import JSONResponse

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-token")
BACKEND_VERSION = os.getenv("BACKEND_VERSION", "0.0.1")

app = FastAPI(title="Bank PDF Converter (MVP)")

COUNTS = {"conversions_today": 0, "ocr_calls_today": 0}

@app.get("/")
def root():
    return {"status": "backend live"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/version")
def version():
    return {"version": BACKEND_VERSION}

@app.get("/stats")
def stats(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth")
    token = authorization.split(" ", 1)[1].strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return {
        "conversions_today": COUNTS["conversions_today"],
        "ocr_calls_today": COUNTS["ocr_calls_today"],
    }

@app.post("/convert")
async def convert(bank: str = Form(...), file: UploadFile | None = None):
    if not file:
        return JSONResponse({"error": "No file uploaded"}, status_code=400)
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        return JSONResponse({"error": "Only PDF files are allowed"}, status_code=400)
    content = await file.read()
    if len(content) > 10_000_000:
        return JSONResponse({"error": "File too large (max 10MB)"}, status_code=400)

    COUNTS["conversions_today"] += 1
    return {
        "message": "File received successfully",
        "bank": bank,
        "filename": file.filename,
        "size_bytes": len(content),
    }
