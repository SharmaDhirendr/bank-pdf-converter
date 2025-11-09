import io, os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

import pandas as pd
import pdfplumber
from pypdf import PdfReader, PdfWriter

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-token")
BACKEND_VERSION = os.getenv("BACKEND_VERSION", "0.0.1")

app = FastAPI(title="Bank PDF Converter (MVP)")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

COUNTS = {"conversions_today": 0, "ocr_calls_today": 0}

@app.get("/")
def root(): return {"status": "backend live"}
@app.get("/health")
def health(): return {"ok": True}
@app.get("/version")
def version(): return {"version": BACKEND_VERSION}
@app.get("/stats")
def stats(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth")
    if authorization.split(" ",1)[1].strip() != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return COUNTS

# -------- helpers --------
def _parse_date(d: str|None) -> str|None:
    if not d: return None
    d = d.strip()
    for fmt in ("%d/%m/%Y","%d/%m/%y","%d-%b-%y","%d-%b-%Y"):
        try: return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
        except: pass
    return None

def _to_float(x) -> float|None:
    if x is None: return None
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace(",","").strip()
    if s in ("","-","--"): return None
    try: return float(s)
    except: return None

def maybe_decrypt(pdf_bytes: bytes, password: Optional[str]) -> bytes:
    if not password: return pdf_bytes
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if reader.is_encrypted and reader.decrypt(password) == 0:
        raise ValueError("Incorrect PDF password.")
    w = PdfWriter()
    for p in reader.pages: w.add_page(p)
    out = io.BytesIO(); w.write(out); return out.getvalue()

HDFC_HEADERS = {
    "date": {"date","txn date","transaction date"},
    "narration": {"narration","description","particulars","remarks"},
    "refno": {"chq/ref no.","ref no.","cheque no","cheque/ref no","utr no","rrn"},
    "debit": {"withdrawal amt.","withdrawal amount","debit","withdrawal"},
    "credit": {"deposit amt.","deposit amount","credit","deposit"},
}
def _match_field(headers_row, key):
    low = [(h or "").strip().lower() for h in headers_row]
    for i,h in enumerate(low):
        if any(alias in h for alias in HDFC_HEADERS[key]): return i
    return None

def parse_hdfc_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for tbl in (page.extract_tables() or []):
                if not tbl or len(tbl) < 2: continue
                hdr = tbl[0]
                i_date=_match_field(hdr,"date"); i_narr=_match_field(hdr,"narration")
                i_ref=_match_field(hdr,"refno"); i_deb=_match_field(hdr,"debit")
                i_cred=_match_field(hdr,"credit")
                if i_date is None or (i_deb is None and i_cred is None): continue
                for r in tbl[1:]:
                    def safe(i): return r[i] if i is not None and i < len(r) else None
                    date=_parse_date(safe(i_date))
                    narr=(safe(i_narr) or "").strip()
                    ref =(safe(i_ref) or "").strip()
                    deb =_to_float(safe(i_deb)) or 0.0
                    cre =_to_float(safe(i_cred)) or 0.0
                    if not (date and (deb or cre or narr or ref)): continue
                    if "total" in (narr.lower() if narr else ""): continue
                    rows.append({
                        "Date": date,
                        "Narration": narr or ref,
                        "RefNo": ref,
                        "Debit": deb,
                        "Credit": cre,
                        "Balance": ""  # Tally can compute/ignore
                    })
    if not rows:
        raise ValueError("No statement table found (if scanned, OCR comes next).")
    return pd.DataFrame(rows, columns=["Date","Narration","RefNo","Debit","Credit","Balance"])

# -------- main API --------
@app.post("/convert")
async def convert(
    bank: str = Form(...),
    file: UploadFile | None = None,
    password: str | None = Form(default=None),
):
    if not file: return JSONResponse({"error":"No file uploaded"}, status_code=400)
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        return JSONResponse({"error":"Only PDF files are allowed"}, status_code=400)
    raw = await file.read()
    if len(raw) > 12_000_000:
        return JSONResponse({"error":"File too large (max 12MB)"}, status_code=400)

    try:
        data = maybe_decrypt(raw, password)
        if bank.strip().upper()=="HDFC":
            df = parse_hdfc_pdf(data)
        else:
            return JSONResponse({"error":f"Bank '{bank}' not supported yet. Use HDFC."}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Parse failed: {e}"}, status_code=422)

    COUNTS["conversions_today"] += 1
    buf = io.BytesIO(); df.to_csv(buf, index=False); buf.seek(0)
    suggested = os.path.splitext(file.filename or "statement.pdf")[0] + "_tally.csv"
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{suggested}"'}
    )
