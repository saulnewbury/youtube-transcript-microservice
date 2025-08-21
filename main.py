from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from youtube_transcript_api import YouTubeTranscriptApi
import re
import uvicorn
import requests
from typing import Optional, List
import logging
import json
import shelve
import time  # For cache timestamps
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type  # For backoff

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Transcript API with Shorts Support", version="1.1.0")

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
    force_fallback: Optional[bool] = False

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
    is_shorts: bool = False
    transcript_source: str = "direct"

# Cache settings
CACHE_FILE = 'transcript_cache.db'
CACHE_EXPIRY_SECONDS = 30 * 24 * 60 * 60  # 30 days

def get_cached_transcript(video_id: str) -> Optional[dict]:
    try:
        with shelve.open(CACHE_FILE) as cache:
            if video_id in cache:
                cached_data = cache[video_id]
                if time.time() - cached_data['timestamp'] < CACHE_EXPIRY_SECONDS:
                    logger.info(f"Cache hit for video_id: {video_id}")
                    return cached_data['data']
                else:
                    logger.info(f"Cache expired for video_id: {video_id}")
                    del cache[video_id]
    except Exception as e:
        logger.error(f"Cache read error for {video_id}: {str(e)}")
    return None

def cache_transcript(video_id: str, data: dict):
    try:
        with shelve.open(CACHE_FILE) as cache:
            cache[video_id] = {
                'timestamp': time.time(),
                'data': data
            }
        logger.info(f"Cached transcript for video_id: {video_id}")
    except Exception as e:
        logger.error(f"Cache write error for {video_id}: {str(e)}")

def extract_video_id(url: str) -> tuple[str, bool]:
    """Extract video ID from YouTube URL and detect if it's a Short"""
    is_shorts = False
    
    # YouTube Shorts patterns
    shorts_patterns = [
        r'youtube\.com/shorts/([^&\n?#]+)',
        r'youtu\.be/shorts/([^&\n?#]+)',
    ]
    
    for pattern in shorts_patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), True
    
    # Regular YouTube video patterns
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)',
        r'youtube\.com\/v\/([^&\n?#]+)',
        r'youtube\.com\/.*[?&]v=([^&\n?#]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), False
    
    raise ValueError("Could not extract video ID from URL")

# Create a requests session with browser-like headers and keep-alive
def create_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Connection': 'keep-alive'
    })
    return session

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.exceptions.RequestException, Exception))
)
def get_video_metadata(video_id: str, session: requests.Session) -> dict:
    """Get video metadata including title and check if it's a Short with backoff"""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = session.get(url, timeout=10)
        logger.info(f"Metadata fetch for {video_id} - Status: {response.status_code}")
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch metadata")
        
        content = response.text
        
        # Extract title
        title_match = re.search(r'<title>(.*?) - YouTube</title>', content)
        title = title_match.group(1).strip() if title_match else "YouTube Video"
        
        # Check if it's a Short by looking for specific indicators
        is_shorts = any(indicator in content.lower() for indicator in [
            '"isshort":true',
            '"isshorts":true', 
            'shorts',
            '"videotype":"short"'
        ])
        
        # Try to get duration from page data
        duration_match = re.search(r'"lengthSeconds":"(\d+)"', content)
        duration = int(duration_match.group(1)) if duration_match else 0
        
        return {
            'title': title,
            'is_shorts': is_shorts,
            'duration': duration
        }
    except Exception as e:
        logger.error(f"Metadata error for {video_id}: {str(e)}")
        raise

# Assume process_transcript_segments is defined elsewhere in your code (from the truncated part)
# For completeness, I'll stub it if not present, but use your original.
def process_transcript_segments(transcript_data, include_timestamps, timestamp_format):
    # Stub: Implement based on your original logic
    final_text = " ".join([seg['text'] for seg in transcript_data])
    segments = []  # Process as needed
    total_duration = sum([seg['duration'] for seg in transcript_data])
    return final_text, segments, total_duration

@app.post("/transcript")
async def get_transcript(request: TranscriptRequest):
    try:
        video_id, is_shorts = extract_video_id(str(request.url))
        logger.info(f"Processing request for video_id: {video_id}, is_shorts: {is_shorts}")
        
        # Check cache first
        cached_data = get_cached_transcript(video_id)
        if cached_data:
            return TranscriptResponse(**cached_data)
        
        session = create_session()
        
        # Fetch metadata with backoff
        metadata = get_video_metadata(video_id, session)
        
        # Transcript fetching with backoff
        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((Exception,))
        )
        def fetch_transcript():
            try:
                # Instantiate the API with the custom session (http_client parameter)
                ytt_api = YouTubeTranscriptApi(http_client=session)
                
                # List available transcripts
                transcript_list = ytt_api.list(video_id)
                
                # Try to find a generated or manual English transcript
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                    transcript_source = "generated"
                except:
                    transcript = transcript_list.find_manually_created_transcript(['en'])
                    transcript_source = "manual"
                
                # Fetch the transcript object
                fetched_transcript = transcript.fetch()
                
                # Extract metadata from the FetchedTranscript object
                language_code = fetched_transcript.language_code
                is_generated = fetched_transcript.is_generated
                
                # Convert to list of dicts for compatibility with your processing logic
                transcript_data = fetched_transcript.to_raw_data()
                
                return transcript_data, language_code, is_generated, transcript_source
            except Exception as e:
                logger.error(f"Transcript fetch error for {video_id}: {str(e)}")
                raise
        
        transcript_data, language_code, is_generated, transcript_source = fetch_transcript()
        
        if not transcript_data:
            raise HTTPException(status_code=404, detail="No transcript data received.")
        
        # Process transcript efficiently
        final_text, segments, total_duration = process_transcript_segments(
            transcript_data, request.include_timestamps, request.timestamp_format or "seconds"
        )
        
        if not final_text:
            raise HTTPException(status_code=404, detail="Transcript text is empty.")
        
        logger.info(f"Successfully processed {len(segments) if segments else len(transcript_data)} segments for {video_id}")
        
        response_data = {
            "text": final_text,
            "segments": segments if request.include_timestamps else None,
            "status": "completed",
            "video_id": video_id,
            "video_title": metadata.get('title', 'YouTube Video'),
            "language_code": language_code,
            "is_generated": is_generated,
            "service": "youtube_transcript_api",
            "total_segments": len(segments) if segments else len(transcript_data),
            "total_duration": total_duration or metadata.get('duration', 0),
            "is_shorts": metadata.get('is_shorts', is_shorts),
            "transcript_source": transcript_source
        }
        
        # Cache the response
        cache_transcript(video_id, response_data)
        
        return TranscriptResponse(**response_data)
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error for {video_id if 'video_id' in locals() else 'unknown'}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Your other endpoints (get_transcript_by_id, get_shorts_transcript_by_id) remain the same, as they call get_transcript

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        log_level="info"
    )