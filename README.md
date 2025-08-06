# youtube-transcript-microservice

## commands:

**Run Python Service**

```
cd youtube-transcription-services
source venv/bin/activate
python main.py
```

**Stand alone test**

```
curl -X POST http://localhost:8001/transcript \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=jN_ZyKAUytQ"}'
```
