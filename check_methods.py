from youtube_transcript_api import YouTubeTranscriptApi
import inspect

print("Available methods in YouTubeTranscriptApi:")
methods = [method for method in dir(YouTubeTranscriptApi) if not method.startswith('_')]
for method in methods:
    print(f"  {method}")

print("\nTrying to get help:")
try:
    help(YouTubeTranscriptApi)
except:
    print("Help not available")

# Let's also check if there are any other classes
import youtube_transcript_api
print(f"\nAll items in youtube_transcript_api module:")
for item in dir(youtube_transcript_api):
    if not item.startswith('_'):
        print(f"  {item}")
