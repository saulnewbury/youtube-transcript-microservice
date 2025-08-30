import os
import random

# Set up all your Webshare proxies
WEBSHARE_PROXIES = [
    "http://yirmygvp:760s1izruzdz@23.95.150.145:6114/",
    "http://yirmygvp:760s1izruzdz@198.23.239.134:6540/",
    "http://yirmygvp:760s1izruzdz@45.38.107.97:6014/",
    "http://yirmygvp:760s1izruzdz@107.172.163.27:6543/",
    "http://yirmygvp:760s1izruzdz@64.137.96.74:6641/",
    "http://yirmygvp:760s1izruzdz@45.43.186.39:6257/",
    "http://yirmygvp:760s1izruzdz@154.203.43.247:5536/",
    "http://yirmygvp:760s1izruzdz@216.10.27.159:6837/",
    "http://yirmygvp:760s1izruzdz@136.0.207.84:6661/",
    "http://yirmygvp:760s1izruzdz@142.147.128.93:6593/"
]

# Set system-wide proxy (rotate randomly)
selected_proxy = random.choice(WEBSHARE_PROXIES)
os.environ['HTTP_PROXY'] = selected_proxy
os.environ['HTTPS_PROXY'] = selected_proxy

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import logging
import re
import requests
from youtube_transcript_api import YouTubeTranscriptApi

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
    include_timestamps: Optional[bool] = True           # Default to True
    timestamp_format: Optional[str] = "minutes"        # Default to minutes
    grouping_strategy: Optional[str] = "smart"         # Default to smart
    min_interval: Optional[int] = 10                   # Default to 10 seconds
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

def create_session():
    session = requests.Session()
    
    # Use the same proxy that was set in environment variables
    proxy_url = os.environ.get('HTTP_PROXY')
    if proxy_url:
        session.proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        logger.info(f"Using proxy: {proxy_url[:30]}...")  # Log partial proxy URL
    
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Connection': 'keep-alive'
    })
    return session

def get_video_metadata(video_id: str, session: requests.Session) -> dict:
    """Get video metadata including title and check if it's a Short"""
    try:
        # Test what IP we're using
        try:
            ip_check = session.get("https://httpbin.org/ip", timeout=5)
            logger.info(f"Current IP: {ip_check.text}")
        except:
            logger.info("Could not check IP")
        
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

def process_transcript_segments(transcript_data, include_timestamps, timestamp_format, grouping_strategy="smart", min_interval=10):
    """
    Process transcript segments with intelligent grouping
    
    Args:
        grouping_strategy: 
            - "time": Fixed time intervals (original approach)
            - "smart": Respect sentence boundaries and natural pauses (recommended)
            - "sentence": Group by complete sentences/thoughts
        min_interval: Minimum seconds between timestamps (prevents too many timestamps)
    """
    
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
                text.endswith((',')) or  # Sometimes commas indicate pauses
                len(text.split()) >= 8)  # Long segments often end thoughts
    
    def has_natural_pause(current_end, next_start, threshold=0.5):
        """Check if there's a natural pause between segments"""
        return (next_start - current_end) > threshold
    
    segments = []
    text_parts = []
    total_duration = 0
    
    if include_timestamps and grouping_strategy in ["smart", "sentence"]:
        current_group_start = None
        current_group_texts = []
        last_timestamp_time = -min_interval  # Allow first timestamp immediately
        
        for i, segment in enumerate(transcript_data):
            start_time = segment.get('start', 0)
            duration = segment.get('duration', 0)
            text = segment.get('text', '').strip()
            end_time = start_time + duration
            
            total_duration = max(total_duration, end_time)
            
            # Start new group if needed
            if current_group_start is None:
                current_group_start = start_time
                current_group_texts = [text]
            else:
                current_group_texts.append(text)
            
            # Check if we should end this group
            should_end_group = False
            
            if grouping_strategy == "smart":
                # End group if:
                # 1. Sentence ends AND enough time has passed
                # 2. There's a natural pause to the next segment
                # 3. We've hit a reasonable time limit (prevent super long groups)
                time_since_last = start_time - last_timestamp_time
                next_segment = transcript_data[i + 1] if i + 1 < len(transcript_data) else None
                
                if (is_sentence_end(text) and time_since_last >= min_interval):
                    should_end_group = True
                elif (next_segment and has_natural_pause(end_time, next_segment.get('start', 0))):
                    should_end_group = True
                elif (start_time - current_group_start) > 25:  # Max 25 seconds per group
                    should_end_group = True
                    
            elif grouping_strategy == "sentence":
                # End group only at clear sentence boundaries
                if is_sentence_end(text) and (start_time - last_timestamp_time) >= min_interval:
                    should_end_group = True
            
            # Create individual segment for metadata
            processed_segment = {
                'text': text,
                'start': start_time,
                'duration': duration,
                'end': end_time,
                'timestamp': format_timestamp(start_time, timestamp_format)
            }
            segments.append(processed_segment)
            
            # End the group if conditions are met
            if should_end_group or i == len(transcript_data) - 1:  # Last segment
                timestamp_str = format_timestamp(current_group_start, timestamp_format)
                grouped_text = " ".join(current_group_texts)
                text_parts.append(f"{timestamp_str} {grouped_text}")
                
                last_timestamp_time = current_group_start
                current_group_start = None
                current_group_texts = []
                
    elif include_timestamps and grouping_strategy == "time":
        # Original time-based approach (keeping for backwards compatibility)
        timestamp_interval = min_interval
        current_group_start = 0
        current_group_texts = []
        
        for segment in transcript_data:
            start_time = segment.get('start', 0)
            duration = segment.get('duration', 0)
            text = segment.get('text', '').strip()
            end_time = start_time + duration
            
            total_duration = max(total_duration, end_time)
            
            if start_time >= current_group_start + timestamp_interval:
                if current_group_texts:
                    timestamp_str = format_timestamp(current_group_start, timestamp_format)
                    grouped_text = " ".join(current_group_texts)
                    text_parts.append(f"{timestamp_str} {grouped_text}")
                
                current_group_start = (start_time // timestamp_interval) * timestamp_interval
                current_group_texts = [text]
            else:
                current_group_texts.append(text)
            
            processed_segment = {
                'text': text,
                'start': start_time,
                'duration': duration,
                'end': end_time,
                'timestamp': format_timestamp(start_time, timestamp_format)
            }
            segments.append(processed_segment)
        
        if current_group_texts:
            timestamp_str = format_timestamp(current_group_start, timestamp_format)
            grouped_text = " ".join(current_group_texts)
            text_parts.append(f"{timestamp_str} {grouped_text}")
            
    elif include_timestamps:
        # Every segment (original behavior)
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
        # No timestamps
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

@app.post("/transcript")
async def get_transcript(request: TranscriptRequest):
    try:
        video_id, is_shorts = extract_video_id(str(request.url))
        logger.info(f"Processing request for video_id: {video_id}, is_shorts: {is_shorts}")
        
        session = create_session()
        
        # Fetch metadata
        metadata = get_video_metadata(video_id, session)
        
        # Get transcript
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
            transcript_data, 
            request.include_timestamps, 
            request.timestamp_format or "minutes",
            request.grouping_strategy or "smart",
            request.min_interval or 10
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
        
        return TranscriptResponse(**response_data)
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error for {video_id if 'video_id' in locals() else 'unknown'}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")