# PRD — AI Audio Editor (V2)

## Overview
Web-based audio editor with deterministic backend processing.

## V1 Scope (shipped)

### Features
- Upload audio (WAV, MP3 ≤100MB)
- Async processing (status: uploading → processing → ready → failed)
- Waveform visualization
- Playback (play/pause/seek)
- Time selection (drag + numeric input)
- Operations:
  - trim (keep selected range, discard the rest)
  - delete (remove selected range, keep the rest)
  - fade_in (apply volume ramp from silence at the start)
  - fade_out (apply volume ramp to silence at the end)
  - gain (adjust amplitude by dB)
  - normalize (peak normalization to target dB level)
- Undo/redo (frontend, linear stack with truncation on branch)
- Export WAV/MP3

### Audio Compatibility
- V1 must support both mono and stereo input files
- All edit operations must preserve channel count unless a future explicit operation changes it
- Sample rate should be preserved whenever possible
- Stereo files are displayed as a single combined waveform in V1: max(abs(L), abs(R)) per peak window
- Processing and export must preserve stereo audio

### Out of Scope (V1)
- split
- remove_silence
- AI editing
- projects system

## V2 Scope

### New Operations
- reverse (reverse entire audio, duration-preserving)
- remove_silence (detect and strip silent segments by threshold + minimum duration)
- extract_channel (extract left or right channel from stereo → mono output)
- swap_channels (swap L/R channels in stereo audio)
- mono_mixdown (mix stereo to mono via (L+R)/2)
- speed (change playback speed 0.25x–4.0x with pitch preservation via FFmpeg atempo)

### Channel Operations
- extract_channel, swap_channels, and mono_mixdown require stereo input (channels=2)
- extract_channel and mono_mixdown change the output channel count (stereo → mono)
- swap_channels preserves stereo
- Backend validates channel count before processing; returns INVALID_PARAMETERS if input is mono

### Speed Operation
- Uses FFmpeg atempo filter (supports 0.5–2.0 natively; factors >2.0 chain two atempo stages)
- Preserves pitch while changing duration (new_duration = original_duration / factor)
- Duration-changing operation (selection is cleared after apply)

### Out of Scope (V2)
- split
- AI editing
- projects system
- per-channel gain/fade
- stereo panning

## Architecture

Frontend:
- React + Vite + TypeScript + Zustand + WaveSurfer

Backend:
- FastAPI
- FFmpeg (primary processor)
- librosa (analysis only: peak detection for normalize)

### Frontend Modules
| Module | Responsibility |
|--------|---------------|
| `api/` | All HTTP calls. No component calls `fetch` directly |
| `store/` | Zustand store: EditorState + assetHistory for undo |
| `audio/` | WaveSurfer.js wrapper. Declarative React interface |
| `editor/` | Operation panel, parameter forms, local validation |
| `layout/` | Shell, upload drop zone, export dialog |

### Backend Modules
| Module | Responsibility |
|--------|---------------|
| `api/` | FastAPI routers. Thin validation, delegates to services |
| `services/` | Business logic: AssetService, OperationService, ExportService |
| `processors/` | Pure DSP functions. File in → file out. No DB, no HTTP |
| `storage/` | Abstraction over local/S3: save(), get_path(), get_url() |

## Data Flow

Upload → processing (async) → waveform → ready → edit (sync) → new asset → export

## Execution Model

### Upload Processing
Async. `POST /api/assets/upload` returns immediately with `{ assetId, status: "processing" }`.
Frontend polls `GET /api/assets/{id}` every 2 seconds until status is `ready` or `failed`.
Backend returns `Retry-After: 2` header on `processing` responses.

### Edit Operations
Synchronous in V1. `POST /api/operations` blocks until the operation completes and returns the full new asset payload.
Most operations use FFmpeg stream filters and complete in <2 seconds for files ≤100MB.
Server-side timeout: 30 seconds. Operations exceeding this return PROCESSING_FAILED.
Response includes `status: "completed"` to enable future async migration without contract changes.

### Export
Synchronous in V1. `POST /api/export` blocks until the export file is ready.

## Undo/Redo Model

### Data Model
- Frontend maintains `assetHistory: string[]` — an ordered list of asset IDs representing the edit chain
- `currentIndex: number` — pointer into assetHistory indicating the current position
- Each asset on the backend has `parentAssetId` linking it to its predecessor

### Undo
- Decrement `currentIndex`, set `currentAssetId` to `assetHistory[currentIndex]`
- Load that asset's waveform and audio
- Clear selection (simpler for V1; restoring selection across undo adds complexity)
- No backend call needed — the previous asset already exists (non-destructive)

### Redo
- Increment `currentIndex`, set `currentAssetId` to `assetHistory[currentIndex]`
- Load that asset's waveform and audio
- Clear selection

### Branching
- If the user undoes to an earlier state and applies a new operation, truncate the forward history
- The orphaned derived assets remain on disk (cleaned up by TTL)

### Page Refresh
- Frontend persists `currentAssetId` in localStorage so it survives refresh
- Backend returns `parentAssetId` on asset responses, allowing the frontend to reconstruct the edit chain by walking parent links from the current asset back to the original
- Selection is not persisted across refresh (cleared on reload)

## Selection Behavior After Edits

### Duration-Changing Operations (trim, delete, remove_silence, speed)
- Clear selection after the operation completes
- Old timestamps are invalid because the audio duration changed

### Duration-Preserving Operations (gain, normalize, fade_in, fade_out, reverse, extract_channel, swap_channels, mono_mixdown)
- Preserve the current selection
- The audio duration did not change, so the selection remains valid

## Key Principles
- Deterministic processing
- Non-destructive editing
- 1-in-1-out operations
- Async upload, sync operations (V1)
- Preserve original channel count
- Never silently downmix stereo to mono

## Risks
- Large file memory usage
- Disk growth (derived assets)
- Waveform latency
- Timestamp drift after duration-changing edits
- Accidental stereo downmix or sample-rate changes
- WaveSurfer re-render flash between operations
- CORS and request body limits for large uploads
- Gain clipping on loud audio without user warning

## Mitigations
- FFmpeg-first (stream filters avoid loading full file into memory)
- TTL cleanup for derived assets (72h since last access; no session concept needed)
- Async upload processing
- Selection reset after duration-changing edits; preserve after duration-preserving edits
- If librosa is used, always load with sr=None and mono=False
- Stereo golden tests from the start
- Preload new waveform before swapping in WaveSurfer to reduce visual flash
- Configure CORS middleware, set request body limits (100MB) in FastAPI and any reverse proxy
- Detect clipping in gain processor: if output peak exceeds 0 dBFS, return a `warning` field in the operation response

## Stereo & Channel Handling

### V1 Support
- The system must support both mono and stereo audio files
- All processing operations must preserve the original channel count
- Stereo files must remain stereo throughout the entire pipeline
- Waveform visualization displays a single combined waveform for stereo audio in V1: max(abs(L), abs(R)) per peak window
- Export must preserve channel count by default

### V1 Limitations
- No per-channel editing (left/right) in V1
- No channel splitting or extraction features exposed to the user
- No dual-channel waveform UI

### Implemented in V2
- extract left/right channel (extract_channel)
- channel swapping (swap_channels)
- mono mixdown (mono_mixdown)
- silence removal (remove_silence)
- reverse audio (reverse)
- speed change with pitch preservation (speed)

### Future (V3+)
The architecture should allow adding these features in future versions:
- split (split audio at a point into two assets)
- per-channel gain/fade
- stereo panning
- AI editing
- projects system
