from youtube_transcript_api import YouTubeTranscriptApi

# Test with a known video
video_id = "jN_ZyKAUytQ"

# Create an instance (required in version 1.2.2+)
api = YouTubeTranscriptApi()

try:
    transcript = api.get_transcript(video_id, languages=['en'])
    print("SUCCESS: Got transcript with", len(transcript), "segments")
    print("First segment:", transcript[0] if transcript else "None")
except Exception as e:
    print("FAILED:", str(e))
    print("Trying without language spec...")
    try:
        transcript = api.get_transcript(video_id)
        print("SUCCESS (no lang): Got transcript with", len(transcript), "segments")
        print("First segment:", transcript[0] if transcript else "None")
    except Exception as e2:
        print("ALSO FAILED:", str(e2))
