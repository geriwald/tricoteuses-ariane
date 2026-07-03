"""Compare 3 transcriptions of the same 3-min clip: Deepgram (batch), Whisper offline, Whisper streaming.
No human ground truth available -> Whisper offline large-v3 is used as pseudo-reference (best of the three).
WER therefore measures DIVERGENCE from Whisper-offline, not absolute truth."""
import json
import re

import jiwer
from faster_whisper import WhisperModel

WAV = "/home/geraud/code/tricoteuses-transcription-videos/audios/RUANR5L17S2026IDC458774-3min.wav"
DG_JSON = "/home/geraud/code/tricoteuses-transcription-videos/out/transcript-deepgram-3min.json"
LIVE_LOG = "/home/geraud/code/whisper-live/live_whisper.log"

# 1. Whisper offline (pseudo-reference)
model = WhisperModel("large-v3", device="cuda", compute_type="float16")
segs, _ = model.transcribe(WAV, language="fr", beam_size=5)
whisper_offline = " ".join(s.text.strip() for s in segs)

# 2. Deepgram batch (full raw transcript)
dg = json.load(open(DG_JSON))
deepgram = dg["metadata"]["raw"]["results"]["channels"][0]["alternatives"][0]["transcript"]

# 3. Whisper streaming (concat of confirmed segments from the live log)
lines = [l for l in open(LIVE_LOG) if ("wall | audio" in l) or l.startswith("[FINAL")]
whisper_stream = " ".join(l.split("]", 1)[1].strip() for l in lines if "]" in l)


def norm(t):
    t = t.lower().replace("<br/>", " ")
    t = re.sub(r"[^\w\sàâäéèêëïîôöùûüç'-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


ref = norm(whisper_offline)
cands = {"Deepgram (batch)": norm(deepgram), "Whisper (streaming)": norm(whisper_stream)}

print(f"pseudo-ref = Whisper offline large-v3 : {len(ref.split())} mots\n")
for name, h in cands.items():
    m = jiwer.process_words(ref, h)
    print(f"{name:22} WER={m.wer*100:5.1f}%  (sub={m.substitutions} del={m.deletions} "
          f"ins={m.insertions}, {len(h.split())} mots)")

dg_vs_stream = jiwer.wer(cands["Deepgram (batch)"], cands["Whisper (streaming)"])
print(f"\nDeepgram vs Whisper-streaming (entre eux) : WER={dg_vs_stream*100:.1f}%")
