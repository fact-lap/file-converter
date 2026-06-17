---
title: File Converter
emoji: 🔄
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# File Converter

Flask/Docker file converter for images, documents, audio, and music notation.

## Music / Notation Lane

Deterministic conversions:

- `.musicxml` / `.xml` / `.mxl` / `.mscz` -> `.pdf`, `.mid`, `.musicxml`, `.mscz`
- `.mid` / `.midi` -> `.pdf`, `.musicxml`, `.mscz`

Draft AI transcription:

- audio (`.mp3`, `.wav`, `.flac`, `.aac`, `.ogg`, `.m4a`, `.opus`, `.wma`) -> `.mid`, `.musicxml`, `.pdf`
- direct mode runs `basic-pitch`
- demucs mode runs `demucs` first, then `basic-pitch`

The audio transcription lane is lossy and should be treated as a draft score for human cleanup.

## Runtime Tools

Required system tools:

- `ffmpeg`
- `musescore3` or another MuseScore CLI available as `MUSESCORE_BIN`

Python dependencies are pinned in `requirements.txt`, including `basic-pitch`, `demucs`, `music21`, `mido`, `librosa`, `pretty_midi`, `torch`, and `torchaudio`.

MuseScore runs headless with:

```bash
QT_QPA_PLATFORM=offscreen
```

## Verified RunPod Phase 0

Verified on RunPod pod `5k6kk9qklo23l0`:

- RTX 4090 / CUDA visible through PyTorch
- MusicXML -> PDF
- MusicXML -> MIDI
- WAV -> MIDI through basic-pitch
- WAV -> MIDI through demucs + basic-pitch
- WAV -> draft PDF through basic-pitch + MuseScore
