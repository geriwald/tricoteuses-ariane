# Ariane

**Weave the live thread of an Assemblée nationale sitting.** Ariane fuses the
speech stream (STT) with the chamber's public referentials (dérouleur, Eliasse,
actors) into a single timestamped, hyperlinked event thread — deducing *what was
said and by whom* and resolving it to canonical IDs, the way the records
directorate (régie) does by hand today.

This repository is the hackathon working base: the product brick plus the
scaffolding needed to run and demonstrate it off a laptop, without capturing in
the hemicycle.

## The four bricks

A single shared **demo clock** drives everything (`t` = ms since sitting start).
Two bricks are the *product*, two are *demo scaffolding* that feed the product a
faithful, **causal** live (never leaking data published after `t`).

| Brick | Role | Kind |
|-------|------|------|
| [`b1-weaver/`](b1-weaver/) | **The weaver.** STT → utterances, projected onto the dérouleur trame, joined with the Eliasse live pointer, resolved to canonical IDs → one append-only `thread.ndjson`. The only brick that outlives the hackathon. | product |
| [`b2-replay/`](b2-replay/) | **Causal replayer.** Serves a recorded sitting (sources + audio + video) under the clock, gated `wall ≤ t`, on the same HTTP shape the live AN endpoints expose — so B1 cannot tell replay from live. | scaffolding |
| [`b3-capture/`](b3-capture/) | **Capture.** Records a live sitting's four sources (dérouleur, Eliasse, NVS, video) with wall-clock stamps and sha1 dedup, then resolves referentials into a frozen snapshot. Produces the bundles B2 replays. | scaffolding |
| [`b4-ui/`](b4-ui/) | **UI.** Static page: clickable thread + video inset + waveform, plus a fenced NVS ground-truth pane for validation (never a B1 input). | product (consumer) |

Full rationale and data model: [`docs/specs/2026-06-26-hackathon-mockup-architecture-design.md`](docs/specs/2026-06-26-hackathon-mockup-architecture-design.md).

**Design invariant.** The thread is *deduced from speech*, never parroted from
the régie's hand-keyed flows (dérouleur highlight, live NVS). Public lists serve
only as lookup referentials to resolve what was *heard* into canonical IDs. The
NVS is ground truth for comparison, never an input.

## Layout

```
b1-weaver/    the weaver (pure cores + live wiring) — tested
b2-replay/    causal replayer / mock AN endpoints  — tested
b3-capture/   live capture + referential resolution — tested
b4-ui/        static UI + tiny anchor proxy
demo/         causal-replay mockup + a replayable fixture
docs/specs/   design specs (the what/why and the how)
docs/data/    what data is available live, and how referentials resolve
spikes/       the STT + speaker-identification exploration (Deepgram vs Whisper)
```

## Running

Python 3.13. The only third-party dependency of the bricks is `numpy` (plus
`pytest` to run the tests). B1's live STT additionally needs a GPU whisper stack
(see below).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install numpy pytest
```

Run the tests:

```bash
cd b1-weaver && python -m pytest -q     # 54 tests
cd b2-replay && python -m pytest -q     # 51 tests
cd b3-capture && python -m pytest -q    #  8 tests
```

Typical demo loop (replay a captured sitting and weave it):

```bash
# B2: replay a capture bundle under the clock
python3 b2-replay/server.py --record path/to/record --port 8000

# B1: weave the thread off B2's video, resolving against referentials
python3 b1-weaver/weaver_live.py --source http://127.0.0.1:8000/video \
    --agenda http://127.0.0.1:8000/derouleur.json --port 8100

# B4: serve the UI
python3 b4-ui/serve.py --port 8080     # open http://127.0.0.1:8080
```

## Configuration

Copy [`.env.sample`](.env.sample) to `.env` (gitignored) if you need it:

- `DEEPGRAM_API_KEY` — only for the transcription **spike**; the bricks don't
  call Deepgram directly.
- `WHISPER_STREAMING_PATH` — B1's live STT reuses
  [`ufal/whisper_streaming`](https://github.com/ufal/whisper_streaming)
  (LocalAgreement). Point this at your clone; defaults to
  `~/code/whisper-live/whisper_streaming`.
- `NOTIFY_SEND` — optional B3 push-notification hook (reads a message on stdin);
  unset = no notification.

## The Tricoteuses ecosystem

Ariane resolves canonical IDs against the open-data **Tricoteuses Parlement REST
API** (`parlement.tricoteuses.fr`) and slots in as a maillon of the transcription
pipeline. The ecosystem it draws on is catalogued in
[`forgejo.json`](forgejo.json).
