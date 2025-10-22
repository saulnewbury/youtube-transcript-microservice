from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import logging
import re
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Transcript API with Shorts Support", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global connection pool - this is the key addition
class TranscriptSessionPool:
    def __init__(self):
        self.proxy_config = WebshareProxyConfig(
            proxy_username="yirmygvp-rotate",
            proxy_password="760s1izruzdz",
        )
        self.ytt_api = YouTubeTranscriptApi(proxy_config=self.proxy_config)
        logger.info("Initialized persistent transcript session pool")
    
    def get_api(self):
        return self.ytt_api

# Create global instance at startup
transcript_pool = TranscriptSessionPool()

class TranscriptRequest(BaseModel):
    url: HttpUrl
    include_timestamps: Optional[bool] = True
    timestamp_format: Optional[str] = "minutes"
    grouping_strategy: Optional[str] = "smart"
    min_interval: Optional[int] = 10
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

def process_transcript_segments(transcript_data, include_timestamps, timestamp_format, grouping_strategy="smart", min_interval=10):
    """Process transcript segments with intelligent grouping"""
    
    def format_timestamp(seconds, format_type="seconds"):
        if format_type == "seconds":
            return f"[{seconds:.1f}s]"
        elif format_type == "minutes":
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"[{minutes}:{secs:02d}]"
        elif format_type == "hms":
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            if hours > 0:
                return f"[{hours}:{minutes:02d}:{secs:02d}]"
            else:
                return f"[{minutes}:{secs:02d}]"
        else:
            return f"[{seconds:.1f}s]"
    
    def is_sentence_end(text):
        """Check if text ends with sentence-ending punctuation or pause indicators"""
        text = text.strip()
        return (text.endswith(('.', '!', '?', '...')) or 
                text.endswith((',')) or
                len(text.split()) >= 8)
    
    def has_natural_pause(current_end, next_start, threshold=0.5):
        """Check if there's a natural pause between segments"""
        return (next_start - current_end) > threshold
    
    segments = []
    text_parts = []
    total_duration = 0
    
    if include_timestamps and grouping_strategy in ["smart", "sentence"]:
        current_group_start = None
        current_group_texts = []
        last_timestamp_time = -min_interval
        
        for i, segment in enumerate(transcript_data):
            start_time = segment.get('start', 0)
            duration = segment.get('duration', 0)
            text = segment.get('text', '').strip()
            end_time = start_time + duration
            
            total_duration = max(total_duration, end_time)
            
            if current_group_start is None:
                current_group_start = start_time
                current_group_texts = [text]
            else:
                current_group_texts.append(text)
            
            should_end_group = False
            
            if grouping_strategy == "smart":
                time_since_last = start_time - last_timestamp_time
                next_segment = transcript_data[i + 1] if i + 1 < len(transcript_data) else None
                
                if (is_sentence_end(text) and time_since_last >= min_interval):
                    should_end_group = True
                elif (next_segment and has_natural_pause(end_time, next_segment.get('start', 0))):
                    should_end_group = True
                elif (start_time - current_group_start) > 25:
                    should_end_group = True
                    
            elif grouping_strategy == "sentence":
                if is_sentence_end(text) and (start_time - last_timestamp_time) >= min_interval:
                    should_end_group = True
            
            processed_segment = {
                'text': text,
                'start': start_time,
                'duration': duration,
                'end': end_time,
                'timestamp': format_timestamp(start_time, timestamp_format)
            }
            segments.append(processed_segment)
            
            if should_end_group or i == len(transcript_data) - 1:
                timestamp_str = format_timestamp(current_group_start, timestamp_format)
                grouped_text = " ".join(current_group_texts)
                text_parts.append(f"{timestamp_str} {grouped_text}")
                
                last_timestamp_time = current_group_start
                current_group_start = None
                current_group_texts = []
                
    elif include_timestamps:
        for segment in transcript_data:
            start_time = segment.get('start', 0)
            duration = segment.get('duration', 0)
            text = segment.get('text', '').strip()
            end_time = start_time + duration
            
            total_duration = max(total_duration, end_time)
            
            processed_segment = {
                'text': text,
                'start': start_time,
                'duration': duration,
                'end': end_time,
                'timestamp': format_timestamp(start_time, timestamp_format)
            }
            segments.append(processed_segment)
            
            timestamp_str = format_timestamp(start_time, timestamp_format)
            text_parts.append(f"{timestamp_str} {text}")
    else:
        for segment in transcript_data:
            start_time = segment.get('start', 0)
            duration = segment.get('duration', 0)
            text = segment.get('text', '').strip()
            end_time = start_time + duration
            
            total_duration = max(total_duration, end_time)
            
            processed_segment = {
                'text': text,
                'start': start_time,
                'duration': duration,
                'end': end_time,
                'timestamp': format_timestamp(start_time, timestamp_format)
            }
            segments.append(processed_segment)
            text_parts.append(text)
    
    final_text = " ".join(text_parts)
    return final_text, segments, total_duration

@app.get("/")
def read_root():
    return {"message": "YouTube Transcript API"}

# In index.py

@app.post("/transcript")
async def get_transcript(request: TranscriptRequest):
    try:
        video_id, is_shorts = extract_video_id(str(request.url))
        logger.info(f"Processing request for video_id: {video_id}, is_shorts: {is_shorts}")
        
        def fetch_transcript():
            try:
                ytt_api = transcript_pool.get_api()
                
                # List available transcripts
                transcript_list = ytt_api.list(video_id)
                
                # Get the first available transcript (any language)
                try:
                    # Try to get any generated transcript first
                    available_transcripts = list(transcript_list._generated_transcripts.values())
                    if available_transcripts:
                        transcript = available_transcripts[0]
                        transcript_source = "generated"
                    else:
                        # Fall back to manual transcripts
                        available_transcripts = list(transcript_list._manually_created_transcripts.values())
                        if available_transcripts:
                            transcript = available_transcripts[0]
                            transcript_source = "manual"
                        else:
                            raise HTTPException(status_code=404, detail="No transcripts available for this video")
                    
                    logger.info(f"Found transcript in language: {transcript.language_code}")
                    
                except Exception as e:
                    logger.error(f"Error accessing transcripts: {str(e)}")
                    raise HTTPException(status_code=404, detail="No transcripts available for this video")
                
                # Fetch the transcript object
                fetched_transcript = transcript.fetch()
                
                # Extract metadata from the FetchedTranscript object
                language_code = fetched_transcript.language_code
                is_generated = fetched_transcript.is_generated
                
                # Convert to list of dicts for compatibility
                transcript_data = fetched_transcript.to_raw_data()
                
                return transcript_data, language_code, is_generated, transcript_source
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Transcript fetch error for {video_id}: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Transcript fetch failed: {str(e)}")
        
        transcript_data, language_code, is_generated, transcript_source = fetch_transcript()
        
        if not transcript_data:
            raise HTTPException(status_code=404, detail="No transcript data received.")
        
        # Process transcript
        final_text, segments, total_duration = process_transcript_segments(
            transcript_data, 
            request.include_timestamps, 
            request.timestamp_format or "minutes",
            request.grouping_strategy or "smart",
            request.min_interval or 10
        )
        
        if not final_text:
            raise HTTPException(status_code=404, detail="Transcript text is empty.")
        
        logger.info(f"Successfully processed {len(segments) if segments else len(transcript_data)} segments for {video_id} (language: {language_code})")
        
        response_data = {
            "text": final_text,
            "segments": segments if request.include_timestamps else None,
            "status": "completed",
            "video_id": video_id,
            "video_title": "YouTube Video",
            "language_code": language_code,
            "is_generated": is_generated,
            "service": "youtube_transcript_api",
            "total_segments": len(segments) if segments else len(transcript_data),
            "total_duration": total_duration,
            "is_shorts": is_shorts,
            "transcript_source": transcript_source
        }
        
        return TranscriptResponse(**response_data)
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error for {video_id if 'video_id' in locals() else 'unknown'}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Optional: Add endpoint to check connection pool health
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "youtube_transcript_api",
        "connection_pool": "active"
    }