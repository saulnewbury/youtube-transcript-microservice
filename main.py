
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from youtube_transcript_api import YouTubeTranscriptApi
import re
import uvicorn
from typing import Optional, List

app = FastAPI(title="YouTube Transcript API", version="1.0.0")

# CORS setup for Next.js
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
    timestamp_format: Optional[str] = "seconds"  # "seconds", "minutes", or "timecode"

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
    """Format timestamp in different ways"""
    if format_type == "seconds":
        return f"[{seconds:.1f}s]"
    elif format_type == "minutes":
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"[{minutes:02d}:{secs:04.1f}]"
    elif format_type == "timecode":
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        if hours > 0:
            return f"[{hours:02d}:{minutes:02d}:{secs:04.1f}]"
        else:
            return f"[{minutes:02d}:{secs:04.1f}]"
    else:
        return f"[{seconds:.1f}s]"

@app.get("/")
async def root():
    return {"message": "YouTube Transcript API with Timestamps", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/transcript", response_model=TranscriptResponse)
async def get_transcript(request: TranscriptRequest):
    try:
        # Extract video ID
        video_id = extract_video_id(str(request.url))
        print(f"🔍 Processing video ID: {video_id}")
        print(f"⏱️  Include timestamps: {request.include_timestamps}")
        print(f"📅 Timestamp format: {request.timestamp_format}")
        
        # Create API instance
        api = YouTubeTranscriptApi()
        
        # Try to get transcript
        transcript_data = None
        language_code = 'unknown'
        is_generated = True
        
        try:
            # Method 1: Use list() to find best transcript
            print("🔄 Trying list method...")
            transcript_list = api.list(video_id)
            
            # Try to get manually created English transcript
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
                language_code = 'en'
                is_generated = False
                print("✅ Found manually created English transcript")
            except:
                # Try auto-generated English
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                    language_code = 'en'
                    is_generated = True
                    print("✅ Found auto-generated English transcript")
                except:
                    # Try any English variant
                    try:
                        transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                        language_code = getattr(transcript, 'language_code', 'en')
                        is_generated = getattr(transcript, 'is_generated', True)
                        print(f"✅ Found English variant: {language_code}")
                    except:
                        # Get first available
                        available = list(transcript_list)
                        if available:
                            transcript = available[0]
                            language_code = getattr(transcript, 'language_code', 'unknown')
                            is_generated = getattr(transcript, 'is_generated', True)
                            print(f"✅ Using first available: {language_code}")
                        else:
                            raise Exception("No transcripts available")
            
            # Fetch the transcript data
            transcript_data = transcript.fetch()
            print(f"📊 Fetched {len(transcript_data)} segments")
            
        except Exception as e:
            print(f"❌ List method failed: {e}")
            try:
                # Method 2: Direct fetch
                print("🔄 Trying direct fetch...")
                transcript_data = api.fetch(video_id)
                language_code = 'unknown'
                is_generated = True
                print(f"✅ Direct fetch got {len(transcript_data)} segments")
            except Exception as e2:
                print(f"❌ Direct fetch failed: {e2}")
                
                # Check for specific errors
                error_str = f"{str(e)} | {str(e2)}"
                if any(x in error_str for x in ["No transcripts", "TranscriptsDisabled", "NoTranscriptFound"]):
                    raise HTTPException(
                        status_code=404,
                        detail="No transcripts found for this video. The video may not have captions available."
                    )
                elif any(x in error_str for x in ["VideoUnavailable", "VideoUnplayable", "private"]):
                    raise HTTPException(
                        status_code=404,
                        detail="Video is unavailable, private, or deleted."
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to access video transcripts: {error_str}"
                    )
        
        # Convert transcript data to text and segments
        if not transcript_data:
            raise HTTPException(
                status_code=404,
                detail="No transcript data received."
            )
        
        # Process transcript segments
        segments = []
        text_parts = []
        total_duration = 0.0
        
        print(f"🔄 Processing {len(transcript_data)} segments...")
        print(f"📝 Include timestamps in text: {request.include_timestamps}")
        
        for i, item in enumerate(transcript_data):
            if hasattr(item, 'text') and hasattr(item, 'start'):
                text = item.text.strip()
                start_time = float(getattr(item, 'start', 0))
                duration = float(getattr(item, 'duration', 0))
                end_time = start_time + duration
                
                if text:  # Only include non-empty text
                    # Create timestamp
                    timestamp = format_timestamp(start_time, request.timestamp_format or "seconds")
                    
                    # Debug: Print first few segments
                    if i < 3:
                        print(f"📄 Segment {i}: start={start_time:.1f}s, text='{text[:50]}...', timestamp='{timestamp}'")
                    
                    # Create segment object
                    segment = TranscriptSegment(
                        text=text,
                        start=start_time,
                        duration=duration,
                        end=end_time,
                        timestamp=timestamp
                    )
                    segments.append(segment)
                    
                    # Add to text with or without timestamps
                    if request.include_timestamps:
                        formatted_text = f"{timestamp} {text}"
                        text_parts.append(formatted_text)
                        if i < 3:  # Debug first few
                            print(f"✅ Added with timestamp: '{formatted_text[:80]}...'")
                    else:
                        text_parts.append(text)
                        if i < 3:  # Debug first few
                            print(f"✅ Added without timestamp: '{text[:80]}...'")
                    
                    total_duration = max(total_duration, end_time)
        
        # Join all text parts
        final_text = " ".join(text_parts)
        
        if not final_text:
            raise HTTPException(
                status_code=404,
                detail="Transcript text is empty."
            )
        
        # Debug output
        print(f"✅ Successfully processed {len(segments)} segments")
        print(f"⏱️  Total duration: {total_duration:.1f} seconds")
        print(f"📝 Final text length: {len(final_text)} characters")
        print(f"🔍 First 200 chars: '{final_text[:200]}...'")
        print(f"🏷️  Has timestamps: {request.include_timestamps and '[' in final_text}")
        
        return TranscriptResponse(
            text=final_text,
            segments=segments if request.include_timestamps else None,
            status="completed",
            video_id=video_id,
            language_code=language_code,
            is_generated=is_generated,
            service="youtube_transcript_api",
            total_segments=len(segments),
            total_duration=total_duration
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )

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