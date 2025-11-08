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
