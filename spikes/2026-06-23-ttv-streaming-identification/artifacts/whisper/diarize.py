"""Speaker diarization with pyannote on GPU, aligned with the existing Whisper utterances.
No re-transcription: pyannote answers 'who speaks when', then each Whisper utterance gets the
dominant speaker over its [beg,end] interval. Same audio => same time reference."""
import json
import time

import torch
from pyannote.audio import Pipeline

WAV = "/home/geraud/code/tricoteuses-transcription-videos/audios/RUANR5L17S2026IDC458774-3min.wav"
UTT = "/home/geraud/code/whisper-live/interim.ndjson"
OUT = "/home/geraud/code/whisper-live/diarized.ndjson"

print("[load] pyannote/speaker-diarization-3.1 ...", flush=True)
t0 = time.time()
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
pipeline.to(torch.device("cuda"))
print(f"[load] {time.time() - t0:.1f}s", flush=True)

# preload audio in memory (soundfile) to bypass the broken torchcodec (wants CUDA 13)
import soundfile as sf  # noqa: E402
wav_np, sr = sf.read(WAV, dtype="float32")
waveform = torch.from_numpy(wav_np).unsqueeze(0)  # (channel, time)
t1 = time.time()
diar = pipeline({"waveform": waveform, "sample_rate": sr})
print(f"[diarize] {time.time() - t1:.1f}s on GPU", flush=True)

segs = [(turn.start, turn.end, spk) for turn, _, spk in diar.exclusive_speaker_diarization.itertracks(yield_label=True)]
speakers = sorted({s for _, _, s in segs})
print(f"\n{len(speakers)} locuteurs : {speakers}  |  {len(segs)} tours de parole\n", flush=True)


def speaker_for(beg, end):
    best, ov_best = None, 0.0
    for s0, s1, spk in segs:
        ov = max(0.0, min(end, s1) - max(beg, s0))
        if ov > ov_best:
            ov_best, best = ov, spk
    return best


utts = [json.loads(line) for line in open(UTT) if '"utterance"' in line]
with open(OUT, "w") as out:
    for u in utts:
        spk = speaker_for(u.get("beg", 0), u.get("end", 0))
        out.write(json.dumps({"speaker": spk, "beg": u.get("beg"), "end": u.get("end"),
                              "text": u["text"].strip()}, ensure_ascii=False) + "\n")

for u in utts[:16]:
    spk = speaker_for(u.get("beg", 0), u.get("end", 0))
    print(f"[{spk}] {u.get('beg', 0):6.1f}-{u.get('end', 0):6.1f}  {u['text'].strip()[:66]}", flush=True)
print(f"... ({len(utts)} utterances diarisées -> {OUT})", flush=True)
