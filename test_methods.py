from youtube_transcript_api import YouTubeTranscriptApi

video_id = "jN_ZyKAUytQ"
api = YouTubeTranscriptApi()

print("Testing 'list' method:")
try:
    result = api.list(video_id)
    print("SUCCESS with list:", type(result))
    print("Result:", result)
    
    # If list returns a TranscriptList, try to get a transcript
    if hasattr(result, 'find_transcript'):
        try:
            transcript = result.find_transcript(['en'])
            print("Found English transcript:", transcript)
            
            # Try to fetch it
            if hasattr(transcript, 'fetch'):
                data = transcript.fetch()
                print("Fetched data:", len(data), "segments")
                print("First segment:", data[0] if data else "None")
        except Exception as e3:
            print("Transcript selection/fetch failed:", e3)
            
except Exception as e:
    print("List failed:", str(e))

print("\nTesting 'fetch' method:")
try:
    result = api.fetch(video_id)
    print("SUCCESS with fetch:", type(result), len(result) if hasattr(result, '__len__') else "no length")
    print("Result sample:", result[:2] if hasattr(result, '__getitem__') else result)
except Exception as e:
    print("Fetch failed:", str(e))
