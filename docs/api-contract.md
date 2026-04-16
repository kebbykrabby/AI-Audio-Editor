# API Contract (V2)

## Upload
POST /api/assets/upload

Request:
- Content-Type: multipart/form-data
- file: audio file (WAV or MP3, ≤100MB)

Response (202 Accepted):
```json
{
  "assetId": "ast_123",
  "status": "processing"
}
```

Notes:
- Returns immediately. Processing (metadata extraction, waveform generation) happens async.
- Frontend polls GET /api/assets/{id} until status is `ready` or `failed`.

---

## Get Asset
GET /api/assets/{id}

Response (status: processing):
```json
{
  "assetId": "ast_123",
  "type": "original",
  "status": "processing",
  "parentAssetId": null,
  "audioUrl": null,
  "waveformUrl": null,
  "durationSec": null,
  "sampleRate": null,
  "channels": null
}
```
Headers: `Retry-After: 2`

Response (status: ready):
```json
{
  "assetId": "ast_123",
  "type": "original",
  "status": "ready",
  "parentAssetId": null,
  "audioUrl": "/api/assets/ast_123/audio",
  "waveformUrl": "/files/ast_123/waveform.json",
  "durationSec": 90,
  "sampleRate": 44100,
  "channels": 2
}
```

Response (status: failed):
```json
{
  "assetId": "ast_123",
  "type": "original",
  "status": "failed",
  "parentAssetId": null,
  "error": {
    "code": "PROCESSING_FAILED",
    "message": "Unsupported audio format or corrupted file"
  }
}
```

Field reference:
- `type`: `"original"` for uploaded files, `"derived"` for operation outputs
- `parentAssetId`: null for originals, the input asset ID for derived assets
- `status`: one of `"processing"`, `"ready"`, `"failed"`
- `channels`: actual channel count of the audio file (1 = mono, 2 = stereo)
- `sampleRate`: preserved from source file

---

## Audio Stream
GET /api/assets/{id}/audio

Notes:
- Supports range requests (returns 206 Partial Content with Content-Range header)
- Used for seek/playback in WaveSurfer
- Returns 404 if asset is still processing or failed

---

## Execute Operation
POST /api/operations

Request:
```json
{
  "type": "trim",
  "input_asset_id": "ast_123",
  "parameters": {
    "start_sec": 5.2,
    "end_sec": 12.7
  }
}
```

Request body must conform to operations.schema.json.

### Operation Semantics
| Type | Behavior |
|------|----------|
| trim | Keep the selected range (`start_sec` to `end_sec`), discard the rest. Output duration = `end_sec - start_sec`. |
| delete | Remove the selected range (`start_sec` to `end_sec`), keep the rest. Output duration = original - (end_sec - start_sec). |
| fade_in | Apply volume ramp from silence to full volume over `duration_sec` from the start of the audio. |
| fade_out | Apply volume ramp from full volume to silence over `duration_sec` at the end of the audio. |
| gain | Adjust amplitude by `gain_db` decibels across the entire audio. |
| normalize | Peak normalization: scale audio so the peak amplitude matches `target_db`. |
| reverse | Reverse the entire audio. Output duration equals input duration. No parameters. |
| remove_silence | Remove portions below threshold. Parameters: `threshold_db` (default -40), `min_silence_sec` (default 0.5). Output duration ≤ input duration. |
| extract_channel | Extract left or right channel from stereo to mono. Requires stereo input (channels=2). Parameter: `channel` ("left" or "right"). Output is mono. |
| swap_channels | Swap left and right channels. Requires stereo input (channels=2). No parameters. Output preserves stereo. |
| mono_mixdown | Mix stereo audio down to mono ((L+R)/2). Requires stereo input (channels=2). No parameters. Output is mono. |
| speed | Change playback speed by `factor` (0.25–4.0) with pitch preservation. Output duration = input_duration / factor. |

Response (200 OK):
```json
{
  "operationId": "op_456",
  "status": "completed",
  "asset": {
    "assetId": "ast_456",
    "type": "derived",
    "parentAssetId": "ast_123",
    "audioUrl": "/api/assets/ast_456/audio",
    "waveformUrl": "/files/ast_456/waveform.json",
    "durationSec": 7.5,
    "sampleRate": 44100,
    "channels": 2
  }
}
```

Response with clipping warning (gain operation):
```json
{
  "operationId": "op_789",
  "status": "completed",
  "warning": "Output audio clips at 0 dBFS. Consider reducing gain.",
  "asset": {
    "assetId": "ast_789",
    "type": "derived",
    "parentAssetId": "ast_456",
    "audioUrl": "/api/assets/ast_789/audio",
    "waveformUrl": "/files/ast_789/waveform.json",
    "durationSec": 7.5,
    "sampleRate": 44100,
    "channels": 2
  }
}
```

V2 example requests:
```json
// reverse
{"type": "reverse", "parameters": {}}

// remove_silence
{"type": "remove_silence", "parameters": {"threshold_db": -40, "min_silence_sec": 0.5}}

// extract_channel
{"type": "extract_channel", "parameters": {"channel": "left"}}

// swap_channels
{"type": "swap_channels", "parameters": {}}

// mono_mixdown
{"type": "mono_mixdown", "parameters": {}}

// speed
{"type": "speed", "parameters": {"factor": 1.5}}
```

Notes:
- `operationId` is server-generated (used for logging, debugging, future undo-by-operation)
- `status` is `"completed"` in V1 (synchronous). Future async migration will return `"processing"`.
- Operations are synchronous in V1: the request blocks until processing finishes. Server-side timeout: 30 seconds.
- Operations must preserve channel count and sample rate by default, unless the operation explicitly changes them (extract_channel, mono_mixdown).
- `warning` field is optional, present when the processor detects issues (e.g., clipping).
- Channel operations (extract_channel, swap_channels, mono_mixdown) require stereo input; return INVALID_PARAMETERS (422) if the asset is mono.

---

## Export
POST /api/export

Request:
```json
{
  "asset_id": "ast_456",
  "format": "mp3",
  "sample_rate": 44100,
  "bitrate_kbps": 320
}
```

Field reference:
- `format`: `"wav"` or `"mp3"` (required)
- `sample_rate`: 22050, 44100, or 48000 (optional, defaults to source)
- `bitrate_kbps`: 128, 192, 256, or 320 (optional, MP3 only, defaults to 192)

Response (200 OK):
```json
{
  "downloadUrl": "/files/ast_456/export.mp3",
  "format": "mp3",
  "sampleRate": 44100,
  "channels": 2
}
```

Notes:
- Export must preserve channel count by default.
- `bitrate_kbps` is silently ignored for WAV format (not an error).
- Invalid `format`, `sample_rate`, or `bitrate_kbps` values return `INVALID_PARAMETERS` (422).

---

## Errors

All error responses follow this format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description"
  }
}
```

### Error Codes

| Code | HTTP Status | When |
|------|-------------|------|
| INVALID_FILE | 422 | Upload: unsupported format, corrupt file, or exceeds 100MB |
| ASSET_NOT_FOUND | 404 | Asset ID does not exist |
| ASSET_NOT_READY | 409 | Operation or export attempted on an asset with status != ready |
| INVALID_OPERATION | 422 | Operation type not recognized |
| INVALID_PARAMETERS | 422 | Operation parameters fail validation (missing, out of range, wrong type) |
| PROCESSING_TIMEOUT | 504 | Operation exceeded 30 second server-side timeout |
| PROCESSING_FAILED | 500 | FFmpeg/librosa processing crashed unexpectedly |
| EXPORT_FAILED | 500 | Export encoding failed |

### Parameter Validation Errors (422)

Include field-level detail:
```json
{
  "error": {
    "code": "INVALID_PARAMETERS",
    "message": "start_sec must be less than end_sec",
    "details": {
      "field": "start_sec",
      "constraint": "must be < end_sec",
      "received": 10.5
    }
  }
}
```

---

## Server-Side Validation Rules

These constraints cannot be expressed in JSON Schema and must be enforced by the backend. All violations return `INVALID_PARAMETERS` (422).

### Cross-Field Rules
| Rule | Applies To | Error |
|------|-----------|-------|
| `start_sec < end_sec` | trim, delete | "start_sec must be less than end_sec" |
| `end_sec <= asset.durationSec` | trim, delete | "end_sec exceeds audio duration" |
| `start_sec < asset.durationSec` | trim, delete | "start_sec exceeds audio duration" |
| `duration_sec <= asset.durationSec` | fade_in, fade_out | "fade duration exceeds audio duration" |

### Channel Constraint Rules
| Rule | Applies To | Error |
|------|-----------|-------|
| Asset must have channels ≥ 2 | extract_channel, swap_channels | "{op_type} requires stereo audio (2 channels)" |
| Asset must have channels ≥ 2 | mono_mixdown | "mono_mixdown requires stereo audio (2 channels)" |

### Parameter Range Rules
| Rule | Applies To | Error |
|------|-----------|-------|
| `0.25 < factor <= 4.0` | speed | Schema validation (422) |
| `-80 <= threshold_db <= 0` | remove_silence | Schema validation (422) |
| `0 < min_silence_sec <= 10` | remove_silence | Schema validation (422) |

### Output Validity Rules
| Rule | Applies To | Error |
|------|-----------|-------|
| Output duration must be > 0 | delete | "delete range covers entire file; output would be empty" |

### Notes
- The frontend should validate these rules locally for fast UX feedback
- The backend is the authority — never trust frontend validation alone
- The schema (`operations.schema.json`) handles type-level and range-level validation; cross-field and asset-aware rules live in the backend

---

## CORS & Upload Limits

- Backend must configure CORS middleware to allow the frontend origin
- Max request body size: 100MB (configure in FastAPI and any reverse proxy)
- Uploads over 100MB are rejected at the middleware level before buffering

---

## Polling Strategy

For async processing (upload):
- Frontend polls `GET /api/assets/{id}` every 2 seconds
- Backend returns `Retry-After: 2` header when status is `processing`
- Frontend should stop polling after 60 seconds and show a timeout error
- Future: SSE or WebSocket may replace polling
