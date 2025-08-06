from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from youtube_transcript_api import YouTubeTranscriptApi
import re
import uvicorn
import requests
from typing import Optional, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Transcript API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TranscriptRequest(BaseModel):
    url: HttpUrl
    include_timestamps: Optional[bool] = False
    timestamp_format: Optional[str] = "seconds"
    include_metadata: Optional[bool] = True

class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float
    end: float
    timestamp: str

class TranscriptResponse(BaseModel):
    text: str
    segments: Optional[List[TranscriptSegment]] = None
    status: str
    video_id: str
    video_title: Optional[str] = None
    language_code: str
    is_generated: bool
    service: str = "youtube_transcript_api"
    total_segments: int
    total_duration: float

def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
        r'youtube\.com\/v\/([^&\n?#]+)',
        r'youtube\.com\/.*[?&]v=([^&\n?#]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise ValueError("Could not extract video ID from URL")

def format_timestamp(seconds: float, format_type: str = "seconds") -> str:
    """Optimized timestamp formatting"""
    if format_type == "seconds":
        return f"[{seconds:.1f}s]"
    elif format_type == "minutes":
        minutes, secs = divmod(seconds, 60)
        return f"[{int(minutes):02d}:{secs:04.1f}]"
    elif format_type == "timecode":
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"[{int(hours):02d}:{int(minutes):02d}:{secs:04.1f}]"
        else:
            return f"[{int(minutes):02d}:{secs:04.1f}]"
    return f"[{seconds:.1f}s]"

def get_video_title(video_id: str) -> str:
    """Get video title efficiently - can be extended to use caching"""
    try:
        # Simple method to get title without heavy ytdl overhead
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Extract title from page HTML
            match = re.search(r'<title>(.*?) - YouTube</title>', response.text)
            if match:
                return match.group(1).strip()
    except Exception as e:
        logger.warning(f"Could not get video title: {e}")
    return "YouTube Video"  # Fallback

def process_transcript_segments(transcript_data, include_timestamps: bool, timestamp_format: str):
    """Optimized segment processing"""
    if not include_timestamps:
        # Fast path for text-only
        text_only = " ".join(item.text.strip() for item in transcript_data if item.text.strip())
        total_duration = max(
            (float(getattr(item, 'start', 0)) + float(getattr(item, 'duration', 0))) 
            for item in transcript_data
        ) if transcript_data else 0.0
        return text_only, [], total_duration
    
    # Pre-allocate lists for better performance
    text_parts = []
    segments = []
    total_duration = 0.0
    
    for item in transcript_data:
        text = item.text.strip()
        if not text:
            continue
            
        start_time = float(getattr(item, 'start', 0))
        duration = float(getattr(item, 'duration', 0))
        end_time = start_time + duration
        
        timestamp = format_timestamp(start_time, timestamp_format)
        text_parts.append(f"{timestamp} {text}")
        
        segments.append(TranscriptSegment(
            text=text,
            start=start_time,
            duration=duration,
            end=end_time,
            timestamp=timestamp
        ))
        
        total_duration = max(total_duration, end_time)
    
    return " ".join(text_parts), segments, total_duration

@app.get("/")
async def root():
    return {"message": "YouTube Transcript API with Timestamps", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/transcript", response_model=TranscriptResponse)
async def get_transcript(request: TranscriptRequest):
    try:
        video_id = extract_video_id(str(request.url))
        logger.info(f"Processing video ID: {video_id}")
        
        # Get transcript data
        api = YouTubeTranscriptApi()
        transcript_data = None
        language_code = 'unknown'
        is_generated = True
        
        try:
            # Optimized transcript fetching - try most common case first
            transcript_list = api.list(video_id)
            
            # Priority order: manual English > auto English > any English > first available
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
                language_code = 'en'
                is_generated = False
            except:
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                    language_code = 'en'
                    is_generated = True
                except:
                    try:
                        transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                        language_code = getattr(transcript, 'language_code', 'en')
                        is_generated = getattr(transcript, 'is_generated', True)
                    except:
                        # Use first available
                        available = list(transcript_list)
                        if available:
                            transcript = available[0]
                            language_code = getattr(transcript, 'language_code', 'unknown')
                            is_generated = getattr(transcript, 'is_generated', True)
                        else:
                            raise Exception("No transcripts available")
            
            transcript_data = transcript.fetch()
            
        except Exception as e:
            # Fallback to direct fetch
            try:
                transcript_data = api.fetch(video_id)
                language_code = 'unknown'
                is_generated = True
            except Exception as e2:
                error_str = f"{str(e)} | {str(e2)}"
                if any(x in error_str for x in ["No transcripts", "TranscriptsDisabled", "NoTranscriptFound"]):
                    raise HTTPException(status_code=404, detail="No transcripts found for this video.")
                elif any(x in error_str for x in ["VideoUnavailable", "VideoUnplayable", "private"]):
                    raise HTTPException(status_code=404, detail="Video is unavailable, private, or deleted.")
                else:
                    raise HTTPException(status_code=400, detail=f"Failed to access video transcripts: {error_str}")
        
        if not transcript_data:
            raise HTTPException(status_code=404, detail="No transcript data received.")
        
        # Process transcript efficiently
        final_text, segments, total_duration = process_transcript_segments(
            transcript_data, request.include_timestamps, request.timestamp_format or "seconds"
        )
        
        if not final_text:
            raise HTTPException(status_code=404, detail="Transcript text is empty.")
        
        # Get video title if requested
        video_title = None
        if request.include_metadata:
            video_title = get_video_title(video_id)
        
        logger.info(f"Successfully processed {len(segments)} segments")
        
        return TranscriptResponse(
            text=final_text,
            segments=segments if request.include_timestamps else None,
            status="completed",
            video_id=video_id,
            video_title=video_title,
            language_code=language_code,
            is_generated=is_generated,
            service="youtube_transcript_api",
            total_segments=len(segments) if segments else len(transcript_data),
            total_duration=total_duration
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/transcript/{video_id}")
async def get_transcript_by_id(
    video_id: str, 
    include_timestamps: bool = False,
    timestamp_format: str = "seconds"
):
    """Get transcript by video ID directly"""
    fake_url = f"https://www.youtube.com/watch?v={video_id}"
    request = TranscriptRequest(
        url=fake_url, 
        include_timestamps=include_timestamps,
        timestamp_format=timestamp_format
    )
    return await get_transcript(request)

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        log_level="info"
    )