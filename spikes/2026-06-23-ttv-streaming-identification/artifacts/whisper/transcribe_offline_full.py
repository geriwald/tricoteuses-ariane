"""Full Whisper-offline transcription with per-segment timecodes, to check what the delayed pass
recovers vs the live streaming run."""
import json

from faster_whisper import WhisperModel

WAV = "/home/geraud/code/tricoteuses-transcription-videos/audios/RUANR5L17S2026IDC458774-3min.wav"
OUT = "/home/geraud/code/whisper-live/whisper-offline.ndjson"

model = WhisperModel("large-v3", device="cuda", compute_type="float16")
segs, _ = model.transcribe(WAV, language="fr", beam_size=5)
with open(OUT, "w") as f:
    for s in segs:
        f.write(json.dumps({"beg": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()},
                           ensure_ascii=False) + "\n")
print("offline transcription written")
