from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import logging
import re
from youtube_transcript_api import YouTubeTranscriptApi

app = FastAPI(title="YouTube Transcript API", version="1.0.0")

class TranscriptRequest(BaseModel):
    url: HttpUrl

class TranscriptResponse(BaseModel):
    text: str
    video_id: str
    status: str = "completed"

def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)',
        r'youtube\.com\/v\/([^&\n?#]+)',
        r'youtube\.com\/.*[?&]v=([^&\n?#]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise ValueError("Could not extract video ID from URL")

@app.get("/")
def read_root():
    return {"message": "YouTube Transcript API"}

@app.post("/transcript")
async def get_transcript(request: TranscriptRequest) -> TranscriptResponse:
    try:
        video_id = extract_video_id(str(request.url))
        
        # Get transcript
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_generated_transcript(['en'])
        transcript_data = transcript.fetch()
        
        # Join all text
        full_text = " ".join([item['text'] for item in transcript_data])
        
        return TranscriptResponse(
            text=full_text,
            video_id=video_id,
            status="completed"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))