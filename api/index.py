from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional
import logging

app = FastAPI(title="YouTube Transcript API", version="1.0.0")

class TranscriptRequest(BaseModel):
    url: HttpUrl

@app.get("/")
def read_root():
    return {"message": "YouTube Transcript API"}

@app.post("/transcript")
async def get_transcript(request: TranscriptRequest):
    return {"message": f"Would process: {request.url}"}