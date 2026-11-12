import hashlib
import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from db import initialize, activate_or_verify

app = FastAPI(title="Keysystem License API", version="1.0.0")
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN", "")

@app.on_event("startup")
def startup():
    initialize()

class LicenseRequest(BaseModel):
    key: str = Field(min_length=8, max_length=128)
    device_id: str = Field(min_length=8, max_length=256)

def check_api_token(token):
    # Optional shared token. Keep it server-side; do not embed it in a public Lua script.
    if API_ACCESS_TOKEN and token != API_ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/license/activate")
def activate(payload: LicenseRequest):
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,256}", payload.device_id):
        raise HTTPException(status_code=400, detail="invalid_device_id")
    key_hash = hashlib.sha256(payload.key.strip().encode()).hexdigest()
    allowed, status = activate_or_verify(key_hash, payload.device_id)
    return {"valid": allowed, "status": status}

@app.post("/v1/license/verify")
def verify(payload: LicenseRequest):
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,256}", payload.device_id):
        raise HTTPException(status_code=400, detail="invalid_device_id")
    key_hash = hashlib.sha256(payload.key.strip().encode()).hexdigest()
    allowed, status = activate_or_verify(key_hash, payload.device_id)
    return {"valid": allowed, "status": status}
