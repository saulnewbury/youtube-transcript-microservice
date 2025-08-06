from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from youtube_transcript_api import YouTubeTranscriptApi
import re
import uvicorn
from typing import Optional

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

class TranscriptResponse(BaseModel):
    text: str
    status: str
    video_id: str
    language_code: str
    is_generated: bool
    service: str = "youtube_transcript_api"

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

@app.get("/")
async def root():
    return {"message": "YouTube Transcript API is running", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/transcript", response_model=TranscriptResponse)
async def get_transcript(request: TranscriptRequest):
    try:
        # Extract video ID
        video_id = extract_video_id(str(request.url))
        print(f"Processing video ID: {video_id}")
        
        # Create API instance
        api = YouTubeTranscriptApi()
        
        # Try to get transcript
        transcript_data = None
        language_code = 'unknown'
        is_generated = True
        
        try:
            # Method 1: Use list() to find best transcript
            print("Trying list method...")
            transcript_list = api.list(video_id)
            print(f"Found transcript list: {transcript_list}")
            
            # Try to get manually created English transcript
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
                language_code = 'en'
                is_generated = False
                print("Found manually created English transcript")
            except:
                # Try auto-generated English
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                    language_code = 'en'
                    is_generated = True
                    print("Found auto-generated English transcript")
                except:
                    # Try any English variant
                    try:
                        transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                        language_code = getattr(transcript, 'language_code', 'en')
                        is_generated = getattr(transcript, 'is_generated', True)
                        print(f"Found English variant: {language_code}")
                    except:
                        # Get first available
                        available = list(transcript_list)
                        if available:
                            transcript = available[0]
                            language_code = getattr(transcript, 'language_code', 'unknown')
                            is_generated = getattr(transcript, 'is_generated', True)
                            print(f"Using first available: {language_code}")
                        else:
                            raise Exception("No transcripts available")
            
            # Fetch the transcript data
            transcript_data = transcript.fetch()
            print(f"Fetched {len(transcript_data)} segments")
            
        except Exception as e:
            print(f"List method failed: {e}")
            try:
                # Method 2: Direct fetch
                print("Trying direct fetch...")
                transcript_data = api.fetch(video_id)
                language_code = 'unknown'
                is_generated = True
                print(f"Direct fetch got {len(transcript_data)} segments")
            except Exception as e2:
                print(f"Direct fetch failed: {e2}")
                
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
        
        # Convert transcript data to text
        if not transcript_data:
            raise HTTPException(
                status_code=404,
                detail="No transcript data received."
            )
        
        # Extract text from transcript segments
        text_parts = []
        for item in transcript_data:
            if hasattr(item, 'text'):
                text_parts.append(item.text.strip())
            elif isinstance(item, dict) and 'text' in item:
                text_parts.append(item['text'].strip())
            else:
                text_parts.append(str(item).strip())
        
        # Join all text parts
        final_text = " ".join([part for part in text_parts if part])
        
        if not final_text:
            raise HTTPException(
                status_code=404,
                detail="Transcript text is empty."
            )
        
        print(f"Successfully extracted {len(final_text)} characters of text")
        
        return TranscriptResponse(
            text=final_text,
            status="completed",
            video_id=video_id,
            language_code=language_code,
            is_generated=is_generated,
            service="youtube_transcript_api"
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )

@app.get("/transcript/{video_id}")
async def get_transcript_by_id(video_id: str):
    """Get transcript by video ID directly"""
    fake_url = f"https://www.youtube.com/watch?v={video_id}"
    request = TranscriptRequest(url=fake_url)
    return await get_transcript(request)

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        log_level="info"
    )