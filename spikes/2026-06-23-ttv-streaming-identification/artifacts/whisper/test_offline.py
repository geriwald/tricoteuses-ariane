"""Offline Whisper GPU sanity test: transcribe the same 3-min AN clip we sent to Deepgram,
measure real-time factor (RTF), validate Blackwell via CTranslate2."""
import time
from faster_whisper import WhisperModel

WAV = "/home/geraud/code/tricoteuses-transcription-videos/audios/RUANR5L17S2026IDC458774-3min.wav"
MODEL = "large-v3"

t0 = time.time()
model = WhisperModel(MODEL, device="cuda", compute_type="float16")
print(f"[load] {MODEL} on cuda/float16 in {time.time() - t0:.1f}s", flush=True)

t1 = time.time()
segments, info = model.transcribe(WAV, language="fr", beam_size=5)
segs = list(segments)  # force the lazy generator
dt = time.time() - t1
audio = segs[-1].end if segs else 0.0
print(f"[transcribe] {dt:.1f}s for {audio:.0f}s audio  ->  RTF={dt / audio:.3f}  ({audio / dt:.1f}x real-time)", flush=True)
print(f"[info] detected lang={info.language} p={info.language_probability:.2f}, {len(segs)} segments\n", flush=True)
for s in segs[:10]:
    print(f"[{s.start:6.1f}-{s.end:6.1f}] {s.text.strip()}", flush=True)
print(f"... ({len(segs)} segments total)", flush=True)
