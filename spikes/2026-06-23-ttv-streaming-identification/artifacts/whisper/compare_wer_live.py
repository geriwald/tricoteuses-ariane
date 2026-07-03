"""WER live/live : Deepgram streaming vs Whisper streaming, both on the same extract,
against the Whisper-offline pseudo-reference (no human ground truth)."""
import json
import re

import jiwer
from faster_whisper import WhisperModel

WAV = "/home/geraud/code/tricoteuses-transcription-videos/audios/RUANR5L17S2026IDC458774-3min.wav"

model = WhisperModel("large-v3", device="cuda", compute_type="float16")
segs, _ = model.transcribe(WAV, language="fr", beam_size=5)
ref = " ".join(s.text.strip() for s in segs)

dg = " ".join(json.loads(line)["text"] for line in open("deepgram-stream.ndjson") if '"utterance"' in line)
ws = " ".join(json.loads(line)["text"] for line in open("interim.ndjson") if '"utterance"' in line)


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\sàâäéèêëïîôöùûüç'-]", " ", t.lower())).strip()


ref, dg, ws = norm(ref), norm(dg), norm(ws)
print(f"pseudo-ref Whisper offline : {len(ref.split())} mots\n")
print(f"Deepgram STREAMING   WER vs ref = {jiwer.wer(ref, dg) * 100:5.1f}%  ({len(dg.split())} mots)")
print(f"Whisper  STREAMING   WER vs ref = {jiwer.wer(ref, ws) * 100:5.1f}%  ({len(ws.split())} mots)")
print(f"\nDeepgram-stream vs Whisper-stream (entre eux) : {jiwer.wer(dg, ws) * 100:.1f}%")
