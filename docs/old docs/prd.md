# PRD — AI Audio Editor (Technical Product Requirements)

---

## 1. Product Overview

### 1.1 Objective
Build a **web-based audio editor** using React that enables users to:
- upload audio files
- visualize waveform
- perform deterministic edits
- optionally use natural language commands to trigger edits
- export processed audio

### 1.2 Core Principle

> The system executes **deterministic backend audio operations**, while the frontend provides a responsive, state-driven editing interface.

---

## 2. System Goals

### 2.1 Functional Goals
- Audio upload and management
- Waveform visualization and playback
- Manual editing operations
- Operation-based editing pipeline
- Export functionality
- Optional AI → structured edit commands

### 2.2 Engineering Goals
- Client-heavy architecture (React SPA)
- Backend-driven processing
- Strong separation between UI and DSP
- Extensible operation pipeline
- Maintainable modular codebase

---

## 3. System Architecture

### 3.1 High-Level Architecture

```text
React App (Vite)
  ↓
FastAPI Backend
  ↓
Audio Processing Engine (FFmpeg / librosa)
  ↓
Storage (S3-compatible or local)
  ↓
Postgres Database
```

### 3.2 Architectural Principles

#### Deterministic Execution
- All edits are reproducible
- No randomness in processing

#### Non-Destructive Editing
- Original file is immutable
- Each operation creates a new derived asset

#### Operation-Based Editing
- Editing is modeled as a pipeline of operations
- No direct mutation of audio buffers

---

## 4. Frontend Architecture (React)

### 4.1 Stack
- React (Vite)
- TypeScript
- Tailwind CSS
- WaveSurfer.js
- Zustand (state management)

### 4.2 Responsibilities
- UI rendering
- waveform visualization
- playback control
- user interaction
- API communication

### 4.3 Core Components
- `AudioUpload`
- `WaveformViewer`
- `TransportControls`
- `TimelineSelection`
- `OperationPanel`
- `ExportDialog`

### 4.4 State Model

```ts
type EditorState = {
  currentAssetId: string | null
  playbackTime: number
  duration: number
  isPlaying: boolean
  selectionRange: [number, number] | null
  operations: Operation[]
}
```

### 4.5 Frontend Data Flow

```text
Upload → API → Asset Created → Fetch Metadata → Load Waveform → Render UI
```

---

## 5. Backend Architecture

### 5.1 Stack
- FastAPI
- Python
- SQLAlchemy
- Postgres
- FFmpeg
- librosa
- numpy

### 5.2 Responsibilities
- file upload handling
- metadata extraction
- waveform generation
- operation execution
- asset management
- export handling

---

## 6. Storage Layer

### Requirements
- persistent file storage
- scalable
- efficient retrieval

### Structure

```text
/assets/{asset_id}/original.ext
/assets/{asset_id}/waveform.json
/assets/{asset_id}/derived/{version_id}.wav
```

---

## 7. Database Schema

### projects
```sql
id (PK)
name
user_id
created_at
```

### assets
```sql
id (PK)
project_id
type (original | derived)
parent_asset_id
storage_path
waveform_path
duration_sec
sample_rate
channels
created_at
```

### operations
```sql
id (PK)
project_id
input_asset_id
output_asset_id
operation_type
parameters_json
status
created_at
```

---

## 8. Audio Processing Model

### 8.1 Operation Pipeline

```text
input_asset → operation_1 → operation_2 → ... → output_asset
```

### 8.2 Supported Operations (V1)

| Operation | Description |
|---|---|
| trim | keep a time range |
| split | divide audio |
| delete | remove segment |
| fade_in | apply ramp at start |
| fade_out | apply ramp at end |
| gain | adjust amplitude |
| normalize | adjust loudness |

### 8.3 Operation Contract

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

---

## 9. Waveform Processing

### Requirements
- lightweight
- fast generation
- optimized for rendering

### Strategy
- downsample audio signal
- compute peak per window

### Output Format

```json
{
  "samples_per_peak": 512,
  "peaks": [0.1, 0.3, 0.2]
}
```

---

## 10. API Design

### Endpoints

#### Upload Audio
```text
POST /api/assets/upload
```

#### Get Asset
```text
GET /api/assets/{id}
```

#### Execute Operation
```text
POST /api/operations
```

#### Export Audio
```text
POST /api/export
```

### 10.1 Upload Flow

```text
Client uploads file
→ backend validates
→ store file
→ extract metadata
→ generate waveform
→ save DB record
→ return asset payload
```

---

## 11. AI Editing Layer (Optional)

### Role
- Convert natural language into structured operations

### Constraints
- Must not execute operations
- Must produce schema-valid output

### Output Example

```json
{
  "intent": "edit_audio",
  "operations": [],
  "needs_confirmation": false
}
```

### 11.1 Validation Layer
- schema validation
- parameter validation
- operation whitelist enforcement

---

## 12. Execution Engine

### Responsibilities
- validate operation
- load asset
- apply transformation
- store output
- update database

### Execution Mode
- synchronous (V1)
- asynchronous (future)

---

## 13. Performance Considerations

### Waveform
- precomputed server-side

### Processing
- use FFmpeg pipelines
- avoid unnecessary decoding

### File Limits
- initial cap (e.g., 100MB)

---

## 14. Error Handling

### Types
- invalid file
- processing error
- invalid operation

### Strategy
- structured API responses
- logging
- safe retries

---

## 15. Deployment Architecture

### Frontend
- React app (Vite) deployed via static hosting or CDN

### Backend
- containerized FastAPI service

### Storage
- S3-compatible storage or local (dev)

---

## 16. Security
- validate file uploads
- sanitize inputs
- restrict execution environment
- validate operation parameters

---

## 17. Observability
- operation logs
- performance metrics
- error tracking

---

## 18. Future Extensions

### DSP
- denoise
- EQ
- compression

### ML
- stem separation
- beat detection
- key detection

### UI
- multitrack timeline
- advanced editing controls

---

## 19. Summary

This system is:
- a client-heavy React application
- backed by a deterministic audio processing engine
- structured around an extensible operation pipeline

The architecture prioritizes:
- simplicity
- reproducibility
- scalability
