import json
import re
import random
from typing import Optional, List, Dict, Tuple
import requests
import logging

logger = logging.getLogger(__name__)

class YouTubeWebScraper:
    """Scrape YouTube transcripts directly from the website with rotating User-Agents"""
    
    # Diverse User-Agent strings to rotate through
    USER_AGENTS = [
        # Chrome on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        
        # Chrome on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        
        # Firefox on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        
        # Firefox on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0',
        
        # Safari on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        
        # Edge on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        
        # Chrome on Linux
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        
        # Mobile Chrome on Android
        'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
        
        # Mobile Safari on iOS
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    ]
    
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        # Don't set a default User-Agent - we'll set it per request
    
    def _get_headers(self):
        """Get headers with a random User-Agent"""
        user_agent = random.choice(self.USER_AGENTS)
        return {
            'User-Agent': user_agent,
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
    
    def extract_initial_data(self, html: str) -> Dict:
        """Extract the initial YouTube data from the page"""
        pattern = r'var ytInitialData = ({.*?});'
        match = re.search(pattern, html, re.DOTALL)
        
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.error("Failed to parse ytInitialData")
                return {}
        return {}
    
    def extract_player_response(self, html: str) -> Dict:
        """Extract the player response data which contains caption tracks"""
        pattern = r'var ytInitialPlayerResponse = ({.*?});'
        match = re.search(pattern, html, re.DOTALL)
        
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.error("Failed to parse ytInitialPlayerResponse")
                return {}
        return {}
    
    def get_caption_tracks(self, player_response: Dict) -> List[Dict]:
        """Extract available caption tracks from player response"""
        try:
            captions = player_response.get('captions', {})
            player_captions = captions.get('playerCaptionsTracklistRenderer', {})
            caption_tracks = player_captions.get('captionTracks', [])
            return caption_tracks
        except Exception as e:
            logger.error(f"Error extracting caption tracks: {e}")
            return []
    
    def fetch_transcript_from_url(self, caption_url: str) -> List[Dict]:
        """Fetch and parse transcript from YouTube's timedtext API"""
        try:
            # Add format parameter for JSON format
            if '?' in caption_url:
                caption_url += '&fmt=json3'
            else:
                caption_url += '?fmt=json3'
            
            # Use rotating headers for this request too
            response = self.session.get(caption_url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse the transcript segments
            segments = []
            events = data.get('events', [])
            
            for event in events:
                # Skip non-text events
                if 'segs' not in event:
                    continue
                    
                start_ms = event.get('tStartMs', 0)
                duration_ms = event.get('dDurationMs', 0)
                
                # Combine all text segments
                text_parts = []
                for seg in event.get('segs', []):
                    if 'utf8' in seg:
                        text_parts.append(seg['utf8'])
                
                if text_parts:
                    segments.append({
                        'text': ''.join(text_parts).strip(),
                        'start': start_ms / 1000.0,  # Convert to seconds
                        'duration': duration_ms / 1000.0
                    })
            
            return segments
            
        except Exception as e:
            logger.error(f"Error fetching transcript from URL: {e}")
            return []
    
    def fetch_video_page(self, video_id: str) -> str:
        """Fetch the YouTube video page HTML with rotating User-Agent"""
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            headers = self._get_headers()
            logger.info(f"Fetching {video_id} with User-Agent: {headers['User-Agent'][:50]}...")
            
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Error fetching video page: {e}")
            raise
    
    def get_transcript(self, video_id: str, language: str = 'en') -> Tuple[List[Dict], Dict]:
        """
        Main method to get transcript for a video
        Returns (transcript_segments, metadata)
        """
        # Fetch the video page
        html = self.fetch_video_page(video_id)
        
        # Extract player response
        player_response = self.extract_player_response(html)
        
        if not player_response:
            raise ValueError("Could not extract player response from page")
        
        # Get video details
        video_details = player_response.get('videoDetails', {})
        metadata = {
            'title': video_details.get('title', 'Unknown'),
            'author': video_details.get('author', 'Unknown'),
            'length_seconds': int(video_details.get('lengthSeconds', 0)),
            'view_count': video_details.get('viewCount', 'Unknown'),
            'video_id': video_id
        }
        
        # Get caption tracks
        caption_tracks = self.get_caption_tracks(player_response)
        
        if not caption_tracks:
            raise ValueError("No captions available for this video")
        
        # Find the preferred language track
        selected_track = None
        
        # First try to find exact language match
        for track in caption_tracks:
            if track.get('languageCode', '').startswith(language):
                selected_track = track
                break
        
        # If no exact match, try auto-generated
        if not selected_track:
            for track in caption_tracks:
                if track.get('kind') == 'asr' and track.get('languageCode', '').startswith(language):
                    selected_track = track
                    break
        
        # Fall back to first available track
        if not selected_track and caption_tracks:
            selected_track = caption_tracks[0]
            logger.warning(f"Using fallback language: {selected_track.get('languageCode', 'unknown')}")
        
        if not selected_track:
            raise ValueError(f"No transcript found for language: {language}")
        
        # Get the transcript URL
        base_url = selected_track.get('baseUrl')
        if not base_url:
            raise ValueError("No transcript URL found")
        
        # Fetch the actual transcript
        transcript_segments = self.fetch_transcript_from_url(base_url)
        
        metadata['language_code'] = selected_track.get('languageCode', 'unknown')
        metadata['is_generated'] = selected_track.get('kind') == 'asr'
        metadata['track_name'] = selected_track.get('name', {}).get('simpleText', 'Unknown')
        
        return transcript_segments, metadata


# Integration function for your FastAPI app
def fetch_transcript_web_scraping(video_id: str) -> Tuple[List[Dict], str, bool, str]:
    """
    Direct replacement for your existing fetch_transcript function
    
    Returns: (transcript_data, language_code, is_generated, transcript_source)
    """
    scraper = YouTubeWebScraper()
    
    segments, metadata = scraper.get_transcript(video_id, language='en')
    
    # Convert to your expected format
    transcript_data = segments
    language_code = metadata['language_code']
    is_generated = metadata['is_generated']
    transcript_source = 'web_scraping'
    
    return transcript_data, language_code, is_generated, transcript_source


# Modified FastAPI endpoint integration
def modified_fetch_transcript_for_fastapi(video_id: str):
    """
    Drop-in replacement for your current fetch_transcript function in the FastAPI app
    """
    try:
        # Use web scraping instead of youtube-transcript-api
        transcript_data, language_code, is_generated, transcript_source = fetch_transcript_web_scraping(video_id)
        
        if not transcript_data:
            raise ValueError("No transcript data received")
        
        return transcript_data, language_code, is_generated, transcript_source
        
    except Exception as e:
        logger.error(f"Transcript fetch error for {video_id}: {str(e)}")
        raise