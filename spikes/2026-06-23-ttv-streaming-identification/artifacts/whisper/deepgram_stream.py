"""Deepgram live/streaming on the SAME extract as Whisper, for a strict live-vs-live comparison.
Pushes the WAV at 1x (ffmpeg -re) over the Deepgram WebSocket, logs interim + utterances to NDJSON
with the same shape as the Whisper run (type/t/beg/end/text)."""
import asyncio
import json
import re
import sys
import time

import websockets

WAV = "/home/geraud/code/tricoteuses-transcription-videos/audios/RUANR5L17S2026IDC458774-3min.wav"
ENV = "/home/geraud/code/tricoteuses-transcription-videos/.env"
OUT = "/home/geraud/code/whisper-live/deepgram-stream.ndjson"

KEY = None
for line in open(ENV):
    m = re.match(r"^DEEPGRAM_API_KEY=(.+)$", line.strip())
    if m:
        KEY = m.group(1)
assert KEY, "no DEEPGRAM_API_KEY in ttv/.env"

PARAMS = "&".join([
    "model=nova-3", "language=fr", "encoding=linear16", "sample_rate=16000", "channels=1",
    "punctuate=true", "diarize=true", "smart_format=true",
    "interim_results=true", "utterances=true", "utterance_end_ms=1000", "endpointing=300",
])
URL = f"wss://api.deepgram.com/v1/listen?{PARAMS}"


async def main():
    ff = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-i", WAV,
        "-f", "s16le", "-ar", "16000", "-ac", "1", "-",
        stdout=asyncio.subprocess.PIPE,
    )
    out = open(OUT, "w")
    t0 = time.time()
    print("[ready] streaming Deepgram nova-3 (⋯ interim, ✓ utterance)\n", file=sys.stderr, flush=True)

    async with websockets.connect(URL, additional_headers={"Authorization": f"Token {KEY}"}) as ws:
        async def sender():
            while True:
                chunk = await ff.stdout.read(3200)  # ~0.1s @ 16k s16le
                if not chunk:
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    return
                await ws.send(chunk)

        last_interim = ""

        async def receiver():
            nonlocal last_interim
            async for msg in ws:
                m = json.loads(msg)
                if m.get("type") != "Results":  # skip Metadata / UtteranceEnd (channel is a list there)
                    continue
                alt = (m.get("channel", {}).get("alternatives") or [{}])[0]
                txt = (alt.get("transcript") or "").strip()
                if not txt:
                    continue
                now = round(time.time() - t0, 2)
                beg = m.get("start")
                dur = m.get("duration")
                end = round(beg + dur, 2) if (beg is not None and dur is not None) else None
                if m.get("is_final"):
                    sys.stderr.write("\r" + " " * 110 + "\r")
                    print(f"✓ [{beg}] {txt}", file=sys.stderr, flush=True)
                    out.write(json.dumps({"type": "utterance", "t": now, "beg": beg, "end": end, "text": txt},
                                         ensure_ascii=False) + "\n")
                    out.flush()
                    last_interim = ""
                elif txt != last_interim:
                    sys.stderr.write(f"\r⋯ {txt[:108]}")
                    sys.stderr.flush()
                    out.write(json.dumps({"type": "interim", "t": now, "text": txt}, ensure_ascii=False) + "\n")
                    out.flush()
                    last_interim = txt

        await asyncio.gather(sender(), receiver())

    out.close()
    print(f"\n[done] wall-clock {time.time() - t0:.1f}s", file=sys.stderr, flush=True)


asyncio.run(main())
