from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import logging
import re
import requests
from youtube_transcript_api import YouTubeTranscriptApi

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


app = FastAPI(title="YouTube Transcript API", version="1.0.0")

class TranscriptRequest(BaseModel):
    url: HttpUrl
    include_timestamps: Optional[bool] = False

class TranscriptResponse(BaseModel):
    text: str
    video_id: str
    video_title: Optional[str] = None
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

def create_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    return session

def get_video_metadata(video_id: str, session: requests.Session) -> dict:
    """Get video title"""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = session.get(url, timeout=10)
        
        if response.status_code != 200:
            return {'title': 'YouTube Video'}
        
        content = response.text
        title_match = re.search(r'<title>(.*?) - YouTube</title>', content)
        title = title_match.group(1).strip() if title_match else "YouTube Video"
        
        return {'title': title}
    except Exception:
        return {'title': 'YouTube Video'}

@app.get("/")
def read_root():
    return {"message": "YouTube Transcript API"}

@app.post("/transcript")
async def get_transcript(request: TranscriptRequest) -> TranscriptResponse:
    try:
        video_id = extract_video_id(str(request.url))
        session = create_session()
        
        # Get metadata
        metadata = get_video_metadata(video_id, session)
        
        # Get transcript
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_generated_transcript(['en'])
        transcript_data = transcript.fetch()
        
        # Join all text
        full_text = " ".join([item['text'] for item in transcript_data])
        
        return TranscriptResponse(
            text=full_text,
            video_id=video_id,
            video_title=metadata.get('title'),
            status="completed"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))