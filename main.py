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

def get_video_metadata(video_id: str) -> dict:
    """Get video metadata including title and check if it's a Short"""
    try:
        # Try multiple approaches to get video info
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Method 1: Standard watch page
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
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
            
            # Shorts are typically under 60 seconds
            if duration > 0 and duration <= 60:
                is_shorts = True
                
            return {
                'title': title,
                'is_shorts': is_shorts,
                'duration': duration
            }
            
    except Exception as e:
        logger.warning(f"Could not get video metadata: {e}")
    
    return {'title': 'YouTube Video', 'is_shorts': False, 'duration': 0}

def try_alternative_transcript_methods(video_id: str) -> tuple[list, str, bool, str]:
    """Try alternative methods to get transcripts for Shorts"""
    
    # Method 1: Direct API with different language codes
    api = YouTubeTranscriptApi()
    
    # Try more language codes that might be available for Shorts
    language_codes_to_try = [
        ['en', 'en-US', 'en-GB'],
        ['es', 'es-ES', 'es-MX'], 
        ['fr', 'fr-FR'],
        ['de', 'de-DE'],
        ['pt', 'pt-BR'],
        ['ja', 'ja-JP'],
        ['ko', 'ko-KR'],
        ['zh', 'zh-CN', 'zh-TW'],
        ['hi', 'hi-IN'],
        ['ar', 'ar-SA'],
        ['ru', 'ru-RU'],
        ['it', 'it-IT'],
        ['nl', 'nl-NL']
    ]
    
    for lang_group in language_codes_to_try:
        try:
            transcript_list = api.list(video_id)
            
            # Try manual transcripts first
            try:
                transcript = transcript_list.find_manually_created_transcript(lang_group)
                data = transcript.fetch()
                return data, transcript.language_code, False, "manual"
            except:
                pass
            
            # Try generated transcripts
            try:
                transcript = transcript_list.find_generated_transcript(lang_group)
                data = transcript.fetch()
                return data, transcript.language_code, True, "generated"
            except:
                pass
                
        except Exception as e:
            logger.debug(f"Failed to get transcript for languages {lang_group}: {e}")
            continue
    
    # Method 2: Try to get any available transcript
    try:
        transcript_list = api.list(video_id)
        available_transcripts = list(transcript_list)
        
        if available_transcripts:
            # Sort by preference: manual first, then generated
            manual_transcripts = [t for t in available_transcripts if not getattr(t, 'is_generated', True)]
            generated_transcripts = [t for t in available_transcripts if getattr(t, 'is_generated', True)]
            
            for transcript in manual_transcripts + generated_transcripts:
                try:
                    data = transcript.fetch()
                    return data, transcript.language_code, getattr(transcript, 'is_generated', True), "any_available"
                except Exception as e:
                    logger.debug(f"Failed to fetch transcript {transcript.language_code}: {e}")
                    continue
                    
    except Exception as e:
        logger.debug(f"Could not list transcripts: {e}")
    
    # Method 3: Direct fetch as last resort
    try:
        data = api.fetch(video_id)
        return data, 'unknown', True, "direct_fetch"
    except Exception as e:
        logger.debug(f"Direct fetch failed: {e}")
    
    raise Exception("No transcripts available through any method")

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

def process_transcript_segments(transcript_data, include_timestamps: bool, timestamp_format: str):
    """Optimized segment processing"""
    if not include_timestamps:
        # Fast path for text-only
        text_only = " ".join(item['text'].strip() if isinstance(item, dict) else item.text.strip() 
                            for item in transcript_data if (item['text'] if isinstance(item, dict) else item.text).strip())
        total_duration = max(
            (float(item['start'] if isinstance(item, dict) else getattr(item, 'start', 0)) + 
             float(item['duration'] if isinstance(item, dict) else getattr(item, 'duration', 0))) 
            for item in transcript_data
        ) if transcript_data else 0.0
        return text_only, [], total_duration
    
    # Pre-allocate lists for better performance
    text_parts = []
    segments = []
    total_duration = 0.0
    
    for item in transcript_data:
        # Handle both dict and object formats
        if isinstance(item, dict):
            text = item.get('text', '').strip()
            start_time = float(item.get('start', 0))
            duration = float(item.get('duration', 0))
        else:
            text = item.text.strip()
            start_time = float(getattr(item, 'start', 0))
            duration = float(getattr(item, 'duration', 0))
            
        if not text:
            continue
            
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
    return {"message": "YouTube Transcript API with Shorts Support", "version": "1.1.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/transcript", response_model=TranscriptResponse)
async def get_transcript(request: TranscriptRequest):
    try:
        video_id, detected_as_shorts = extract_video_id(str(request.url))
        logger.info(f"Processing video ID: {video_id}, detected as shorts: {detected_as_shorts}")
        
        # Get video metadata
        metadata = get_video_metadata(video_id)
        is_shorts = detected_as_shorts or metadata.get('is_shorts', False)
        
        logger.info(f"Video metadata: title='{metadata['title']}', is_shorts={is_shorts}, duration={metadata.get('duration', 0)}s")
        
        # Try to get transcript data with enhanced methods for Shorts
        transcript_data = None
        language_code = 'unknown'
        is_generated = True
        transcript_source = "direct"
        
        try:
            if is_shorts or request.force_fallback:
                # Use alternative methods for Shorts
                transcript_data, language_code, is_generated, transcript_source = try_alternative_transcript_methods(video_id)
                logger.info(f"Successfully got transcript using {transcript_source} method")
            else:
                # Standard method for regular videos
                api = YouTubeTranscriptApi()
                transcript_list = api.list(video_id)
                
                # Priority order: manual English > auto English > any English > first available
                try:
                    transcript = transcript_list.find_manually_created_transcript(['en'])
                    language_code = 'en'
                    is_generated = False
                    transcript_source = "manual_en"
                except:
                    try:
                        transcript = transcript_list.find_generated_transcript(['en'])
                        language_code = 'en'
                        is_generated = True
                        transcript_source = "generated_en"
                    except:
                        try:
                            transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                            language_code = getattr(transcript, 'language_code', 'en')
                            is_generated = getattr(transcript, 'is_generated', True)
                            transcript_source = "any_en"
                        except:
                            # Use first available
                            available = list(transcript_list)
                            if available:
                                transcript = available[0]
                                language_code = getattr(transcript, 'language_code', 'unknown')
                                is_generated = getattr(transcript, 'is_generated', True)
                                transcript_source = "first_available"
                            else:
                                raise Exception("No transcripts available")
                
                transcript_data = transcript.fetch()
                
        except Exception as e:
            logger.warning(f"Standard method failed: {e}")
            
            # Fallback to alternative methods
            try:
                transcript_data, language_code, is_generated, transcript_source = try_alternative_transcript_methods(video_id)
                logger.info(f"Fallback successful using {transcript_source} method")
            except Exception as e2:
                error_str = f"{str(e)} | {str(e2)}"
                if any(x in error_str.lower() for x in ["no transcripts", "transcriptsdisabled", "notranscriptfound", "could not retrieve"]):
                    raise HTTPException(status_code=404, detail="No transcripts found for this video. YouTube Shorts may have limited transcript availability.")
                elif any(x in error_str.lower() for x in ["videounavailable", "videounplayable", "private"]):
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
        
        logger.info(f"Successfully processed {len(segments) if segments else len(transcript_data)} segments")
        
        return TranscriptResponse(
            text=final_text,
            segments=segments if request.include_timestamps else None,
            status="completed",
            video_id=video_id,
            video_title=metadata.get('title', 'YouTube Video'),
            language_code=language_code,
            is_generated=is_generated,
            service="youtube_transcript_api",
            total_segments=len(segments) if segments else len(transcript_data),
            total_duration=total_duration or metadata.get('duration', 0),
            is_shorts=is_shorts,
            transcript_source=transcript_source
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
    timestamp_format: str = "seconds",
    force_fallback: bool = False
):
    """Get transcript by video ID directly"""
    fake_url = f"https://www.youtube.com/watch?v={video_id}"
    request = TranscriptRequest(
        url=fake_url, 
        include_timestamps=include_timestamps,
        timestamp_format=timestamp_format,
        force_fallback=force_fallback
    )
    return await get_transcript(request)

@app.get("/transcript/shorts/{video_id}")
async def get_shorts_transcript_by_id(
    video_id: str, 
    include_timestamps: bool = False,
    timestamp_format: str = "seconds"
):
    """Get transcript specifically for YouTube Shorts"""
    fake_url = f"https://www.youtube.com/shorts/{video_id}"
    request = TranscriptRequest(
        url=fake_url, 
        include_timestamps=include_timestamps,
        timestamp_format=timestamp_format,
        force_fallback=True  # Always use alternative methods for Shorts
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