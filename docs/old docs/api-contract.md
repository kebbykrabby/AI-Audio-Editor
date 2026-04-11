# API Contract — AI Audio Editor

## Base URL
/api

---

## 1. Upload Audio

POST /api/assets/upload

### Request
- Content-Type: multipart/form-data
- file: audio file (wav/mp3)

### Response
```json
{
  "assetId": "ast_123",
  "projectId": "prj_123",
  "filename": "song.mp3",
  "originalUrl": "/files/ast_123/original.mp3",
  "waveformUrl": "/files/ast_123/waveform.json",
  "durationSec": 92.34,
  "sampleRate": 44100,
  "channels": 2,
  "mimeType": "audio/mpeg"
}
```

---

## 2. Get Asset

GET /api/assets/{id}

### Response
```json
{
  "assetId": "ast_123",
  "projectId": "prj_123",
  "durationSec": 92.34,
  "waveformUrl": "/files/ast_123/waveform.json"
}
```

---

## 3. Execute Operation

POST /api/operations

### Request
```json
{
  "operation_id": "op_123",
  "type": "trim",
  "input_asset_id": "ast_001",
  "parameters": {
    "start_sec": 5.2,
    "end_sec": 12.7
  }
}
```

### Response
```json
{
  "status": "completed",
  "output_asset_id": "ast_002"
}
```

---

## 4. Export Audio

POST /api/export

### Request
```json
{
  "asset_id": "ast_002",
  "format": "mp3"
}
```

### Response
```json
{
  "downloadUrl": "/files/ast_002/export.mp3"
}
```

---

## 5. Errors

### Format
```json
{
  "error": {
    "code": "INVALID_OPERATION",
    "message": "Invalid parameters"
  }
}
```

---

## Notes
- All operations must match operations.schema.json
- Frontend should not assume processing is instant
- Future: async job IDs may replace immediate responses
