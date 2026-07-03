# Hackathon mockup architecture (Ariane) — design

- **Date**: 2026-06-26
- **Status**: draft, awaiting Géraud's validation
- **Mode**: quick-and-dirty functional mockup, runnable on Géraud's machine (serenity)
- **Scope**: issue #10 ("weave the thread") demonstrated end-to-end via causal replay
- **Parent spec**: [`2026-06-12-hyperlinked-session-thread-design.md`](2026-06-12-hyperlinked-session-thread-design.md) (the *what/why*; this is the *how we mock it*)

## Problem

The product thesis is settled: **the thread is the product** (parent spec). What is
missing is a runnable demonstration of issue #10 — fusing the transcript stream with
the canonical databases (amendment called, ballot, article in progress) into a single
timestamped event thread — that a non-engineer (Xavier Tallon, records directorate)
can watch build itself, with video and waveform, on a laptop, without live capture in
the hemicycle.

The constraint that shapes the whole architecture is **causality**: a live system only
ever knows what was published *before now*. A replay that leaks future data (the full
post-production NVS, the final ballot result before the vote) proves nothing. The mock
must reproduce, instant by instant, the information actually available at broadcast time.

## Architecture — four bricks, a clock and a referential snapshot

A single shared **demo clock** drives everything. `t` is milliseconds since sitting
start. Two bricks are the *product* (B1, and B4 as its consumer); two are *demo
scaffolding* (B2 replay, B3 capture) that exist only to feed B1 a faithful, causal
live. Behind them sits a **referential snapshot** — the stable open-data slices
(actors, amendments, documents) pulled once, out of the clock, to resolve the
canonical IDs the live flows carry.

**The clock master is always the flow source, never a consumer** (see "Clock model"
below). In live, `t` is the wall (`t = now`); in replay, **B2 owns `t`** and advances
it at real-time rate. B1 never receives `t` from anyone: it polls causal endpoints
that only ever expose the past, so it cannot tell — and need not know — whether `t`
comes from the wall or from B2.

![Mockup architecture diagram](2026-06-26-hackathon-mockup-architecture.png)

Source of truth: [`2026-06-26-hackathon-mockup-architecture.excalidraw`](2026-06-26-hackathon-mockup-architecture.excalidraw)
(exported to the PNG above).

The NVS plays **two distinct, non-interchangeable roles** — and the design keeps them
strictly apart:
- **NOT a B1 input.** Feeding post-production ground truth into the weaver would (a) leak
  the answer and dishonestly inflate the demo, (b) be late and chunky anyway (hand-keyed,
  arrives in blocks well after the live — measured in the sync log). B1 consumes only
  live-available sources (audio, Eliasse, dérouleur).
- **Full ground-truth feed → B4 only**, *unfiltered* (deliberately not causal), shown in a
  fenced, clearly-labeled comparison pane. It validates Ariane's weave against the official
  thread; it is never an Ariane output.

### B1 — `ariane-weaver` (business brick, the product)

The only brick that survives past the hackathon. Merges, in real time:

- **Audio → utterances**: STT live (Whisper local — sovereign path, validated in the
  spike — or Deepgram), producing provisional then consolidated segments with word-level
  timecodes and a diarized speaker letter.
- **dérouleur.json — the structural trame.** The ordered list of articles, amendments and
  sub-amendments, each line carrying its canonical IDs (`ligne_amendement_uid` Eliasse,
  `depute_tribun_id` of the *registered author*). It gives the **skeleton and the IDs, not
  the live position.** The highlighted block (`ligne_video_highlighted`) is a growing
  structural section, **NOT a live cursor on the line being discussed** — measured
  2026-06-25 (sync log): the block anchors stay fixed for ~25 min while the discussion moves
  through sub-amendments 451→478→511→540 with changing speakers. Reading it as a live cursor
  was a spike hypothesis the live measurement disproved.
- **Eliasse `prochainADiscuter` — the live position pointer.** Which amendment is up now,
  plus its outcome (`sortEnSeance`), state, `placeReference`. This is the live "what now",
  **joined into the dérouleur trame** (by amendment number) to resolve the canonical IDs and
  the registered author, then confirmed against the audio.
- **Scrutins — announced live, resolved post-production.** The records directorate wants
  ballots in the real-time thread (cadrage note 2026-06-29). The live-available part is the
  **ballot announcement** (dérouleur) and the **in-sitting outcome** (`sortEnSeance` /
  vote result as read by the chair); the **consolidated ballot analysis** (per-MP votes,
  `assemblee.scrutins`) is post-production and stays out of the live weave (ground truth only,
  like the NVS). So a `kind: "ballot"` node is emitted live with announcement + outcome, and
  the consolidated analysis link resolves later. Live scrutin sourcing is under investigation
  (data doc) — a dedicated issue tracks it.

So the weave is: **live pointer (Eliasse / audio announcement) → projected onto the dérouleur
trame → canonical IDs + registered author → speaker confirmed by audio/diarization; outcome
from Eliasse.** The NVS is deliberately *not* an input here (see ground-truth role above).

Output: **one** append-only event log, `thread.ndjson`. Hypertext navigation falls out of
the canonical IDs on each node (parent spec, decision 1). No bespoke linking layer.

**Two output projections (not two business bricks):**

1. *State-of-the-art* — an SSE / WebSocket stream of the event log, consumer-agnostic.
2. *Tricoteuses-compatible* — a thin adapter rendering the same events into the
   `{metadata, segments[], speakers[]}` shape that `tricoteuses-transcription-videos`
   produces (batch), so Ariane slots into their ecosystem as a maillon.

### Thread event format (`thread.ndjson`)

One JSON object per line, append-only. Draft schema (to refine on first run):

```json
{ "t": 184500, "wall": "2026-01-19T14:03:04.512", "seq": 42,
  "kind": "utterance|amendment|ballot|article|phase|speaker",
  "state": "provisional|consolidated",
  "text": "…",
  "canonical": { "acteur": "PA…", "tribun": "841701",
                 "amendement_uid": "AMANR5L17PO838901BTC1583P0D1N000040",
                 "scrutin": null, "article": "…" },
  "source": "stt|derouleur|eliasse|nvs|llm",
  "supersedes": 39 }
```

- `state` carries the two-pass model (parent spec, decision 2): `provisional` nodes are
  emitted live and **replaced** (`supersedes`) by `consolidated` ones on the delayed pass.
- `kind: "phase"` with `source: "llm"` covers unlisted phases (tribute, welcome — issue #11).
- A node may carry empty `canonical` fields when the databases are silent; that is the gap
  Ariane fills (issue #9), and it is visible in the UI.

### B2 — `ariane-replay` (source + audio + video simulation, demo only)

Replays a recording produced by B3 (`record/index.ndjson` + `record/raw/<source>/<ts>.*`)
under the shared clock, enforcing causality. One brick now drives **all three replayed
streams** — sources, audio and video — off the single clock (the former B2-sources and
B3-video were the same simulation gated by the same wall-clock; splitting them bought
nothing and risked drift):

- At demo time `t`, serve each source snapshot **only if its wall-clock ≤ t**. Future
  snapshots stay hidden. This is the causality guarantee — the same HTTP shape the live
  sources expose, so B1 cannot tell replay from live.
- Re-exposes `derouleur.json`, `data.nvs`, Eliasse responses as local endpoints B1 polls.
- Serves the **audio** track (wav/HLS extract) and the **video** (VOD `master.m3u8`, or a
  downloaded mp4) on the same clock, so picture, audio and thread stay aligned. The video is
  pure eye-candy for the demo, but it is what makes the causality point legible ("the overlay
  is correct *and* early").

**Clock master inside B2 — and it is the clock, not the video player.** B2 holds a
**master clock** that owns `t`, advances it at real-time rate, and is the single
authority. The video stream is a *slave* of that clock (B2 sets `currentTime` to
follow `t`), **never** the master. Reason: B2 replays five flows at once (dérouleur,
NVS, Eliasse, audio, video); slaving four data flows to a `<video>`/HLS clock — which
is approximate and non-monotonic (buffering, decoder drift, 2-6 s segment granularity)
— would make amendments and ballots flicker to the rhythm of decode hiccups. The master
clock is monotonic, exact, and native to the record (`t = ms since sitting start`); the
data sources are already indexed on it. One authority direction only: clock → video,
re-synced on every seek.

**The UI drives B2 by transport commands, never by pushing `t`.** The UI sends
`play` / `pause` / `seek(t)` / `seek(±Δ)` / `seek(0)`; B2 translates them into clock
movement. A scrub of the `<video>` is one such command (it tells the master clock "go
to `t`"), not a competing clock — which is exactly why the same B1 works in live (no
scrub at all) and in replay.

**Seek backwards = purge downstream of `t`.** B2 is stateless w.r.t. `t` (it re-filters
`wall-clock ≤ t` on each request), so it can serve any `t`, including a smaller one.
On a backward seek, B1/B4 **purge the thread for nodes whose `t` is beyond the new
position** and let it rebuild from there (the `thread.ndjson` format already carries
`seq`/`supersedes`, so truncation by `t` is mechanical). The thread is never
reconstructed incrementally across a *forward* seek either — it simply continues.

Timing fact worth surfacing (measured 2026-06-25, data doc): the **dérouleur and the video
are co-temporal** (~6-7 s apart, same delayed clock) — so there is **no offset to manage**
between the structural trame and the picture in the replay. The **broadcast ↔ true-real-time**
delay (régie production time, the window during which the NVS is hand-keyed — exactly the work
Ariane automates) is **normally ~1 min**; the ~4 min 50 s measured 2026-06-25 was an **atypical
sitting** (corrected with the records directorate 2026-06-29, data doc + cadrage note), to be
re-measured on a normal sitting. Either way it is *not* a lead of the thread over the picture;
the earlier "thread leads the broadcast" framing was wrong. The replay reproduces whatever this
delay was on the recorded day (it is baked into the record's wall-clocks), so the mock stays
faithful regardless of the exact figure.

### B3 — `ariane-capture` (live recorder, demo scaffolding upstream of B2)

The brick that **produces** the recording B2 replays. Polls the live sources of a sitting
under wall-clock stamps and persists each raw snapshot only when its content changed (sha1
dedup), so storage scales with the number of transitions, not ticks (a 4 h sitting → tens of
MB, not gigabytes). Implemented by `record_sitting.py` (the caladan cron runs it unattended).

Sources captured (the live, causal flows):

- **dérouleur** — structural trame + canonical IDs;
- **data.nvs** — NVS ground truth (chapters + effective speakers, tribun id in `<speaker><url>`);
- **liveplayer.nvs** — sync track (`<player starttime>` + `<synchro>`), joins NVS chapters onto
  the video timeline;
- **Eliasse** (`prochainADiscuter`, `amendement`) — live position pointer + `sortEnSeance`.

Output: `record/index.ndjson` (one record per tick: per-source state + `raw_ref` + `changed`
flag) and `record/raw/<source>/<ts>.*` (full raw response, written only on hash change). The
full dérouleur trame is **not** inlined per tick (it would bloat the index); it lives in the
deduped raw `derouleur.json`, read back by B2/B1.

Capture is one-shot per sitting and offline relative to the demo: B3 runs *before* demo day to
build the corpus; B2 and B1 never touch it live. Audio/video for the same sitting are pulled
alongside (HLS/VOD) so B2 has the full bundle to replay.

**Referential resolution is a separate post-capture pass, not part of B3.** B1 does not
run during capture, so no resolver is alive then — but it does not need to be: every
canonical ID the replay will encounter is **already in the captured raw flows** (the
speaker's tribun_id in NVS `<speaker><url>`, the author's `depute_tribun_id` and the
amendment/document uids in the dérouleur). So the snapshot is built *after* capture by a
pass (`resolve_referential.py`): scan the record for the set of tribun_ids
(NVS + dérouleur) and amendment/document uids, resolve them against the **Tricoteuses
Parlement REST API** (`parlement.tricoteuses.fr`, batched `?uid[]=` / `?numNotice=`), and
write `record/referential/{acteurs,organes,amendements,documents}.json`, then freeze it.

**Why post-capture, restated (the reason changed).** The earlier draft said the pass is
decoupled *so capture need not depend on Moulineuse OAuth*. That technical reason is **gone**:
resolution is now a plain unauthenticated HTTP `GET` against the REST API (no Anubis, no
OAuth, no MCP — verified 2026-06-29), so the resolver *could* run in the capture process
without fragility. The pass stays post-capture for the **one remaining reason: causality**.
The referential is stable *within* a sitting but may shift between sitting day and demo day
(amendment rectified, document re-published); resolving live at demo time would inject data
that did not exist on the day — the future-leak the discipline forbids. So we freeze a
referential **contemporary with the sitting** (resolved the same evening / next morning, not
at a distant demo time). The capture (cron, unattended) is the precious artifact; a
resolution failure is re-run later against the same record, the sitting is never lost.

What the snapshot resolves is exactly what carries an ID in the flows. A speaker the NVS
does *not* identify (chair, unkeyed voice) is resolved by no one — that is the #9 gap
Ariane fills by oral attribution, not a snapshot miss.

### Referential snapshot (stable open-data, out of the clock)

Not a runtime brick — a **one-shot snapshot** of the stable referentials the canonical IDs
point to, resolved via the **Tricoteuses Parlement REST API** (`parlement.tricoteuses.fr`,
the same `canutes` data, but the unauthenticated M2M door rather than the Moulineuse MCP).
The live flows carry only *keys*; the labels and links the UI shows come from here:

- **actor** `PA…` = `"PA" + depute_tribun_id` (dérouleur author, NVS `<speaker>`) → `assemblee.acteurs`;
- **amendment** `ligne_amendement_uid` → `assemblee.amendements` (author, group, division);
- **group** `groupePolitiqueRef` `PO…` (carried by the amendment) → `assemblee.organes`;
- **document/text** `texte_bibard` → `assemblee.documents` (proposition, rapport).

`organes` is required (to resolve the `PO…` groups the amendments carry) but was only
implicit in the resolution note — it is now listed explicitly.

**Size is trivial — the resolved slices, not the bases** (measured first-hand,
2026-06-29). The snapshot is built by resolving *only the keys the record actually
carries*, via the REST API which returns flat fields (not the raw `data` JSONB). For the
FIN DE VIE record (text 2915) the frozen snapshot is **≈ 200 KB total**: 702 amendments
132 KB, 136 actors 21 KB, 12 groups 1.5 KB, 3 documents <1 KB. (An earlier estimate of
~22 MB assumed pulling whole-base JSONB slices via Moulineuse; resolving by exact key on the
REST API is ~100× smaller.) The snapshot is negligible next to the HLS/video B2 carries.

Because these are stable, they are snapshotted **once, outside the causality clock** (resolution
method recorded in `docs/data/resolution-referentiels-canutes.md`, verified live 2026-06-26).
B1 reads them to turn IDs into clickable labels; they are never streamed and never gated by `t`.

**Captured at the source, frozen, served as-is in replay.** The snapshot is **part of the
capture bundle** (`record/referential/`), produced by the post-capture resolution pass
(see B3), not a file regenerated on demand at demo time. Rationale is causal: the
referential is stable *within* a sitting but may differ between sitting day and demo day
(an amendment rectified, a re-published document). Resolving from the *current* REST API
state at demo time could inject data that did not exist on the day — the same future-leak
the causality discipline forbids. Freezing a referential contemporary with the sitting
keeps the replay honest. The snapshot is an immutable capture artifact, dated like the
record, not a cache that tracks the live API. **This causal freeze is now the *only* reason
the resolution is post-capture** — the former technical reason (no MCP OAuth in the cron) is
gone, since resolution is plain HTTP (see B3).

**MVP snapshot → prod resolver — one continuum, not two modes.** In the mockup, B1's
resolver is a **pre-filled cache** loaded from the frozen snapshot (never a miss, the API
never called in replay). In production live, the *same* `resolve(uid)` interface adds:
resolve-on-first-miss against the **Tricoteuses Parlement REST API** (`parlement.tricoteuses.fr`
— plain HTTP, no auth, the M2M door; a service cannot depend on the interactive Moulineuse
MCP), a cache held for the sitting (referentials are stable per sitting, no TTL needed),
pre-warmed at sitting start from the dérouleur (which lists the amendments and authors ahead
of time — batched `?uid[]=` covers the bulk), and a degraded label (raw uid, still clickable)
if the API is unreachable so the live thread never stalls. The mockup snapshot is the
**frozen-cache** form of that resolver — the same code grown, nothing thrown away. The
"freeze a sitting's cache to a file" mode *is* the demo mode.

**Week-1 validation (cheap, falsifiable).** The freeze is theoretically required for
causal honesty; whether it matters *in practice* is measurable: on Friday, **diff the
captured snapshot against the current Moulineuse state** for the test sittings. Empty diff →
the referential did not move in a week → freezing was neutral, simplify knowingly. Non-empty
diff → freezing was provably necessary. Either way we learn, having wagered nothing.

### Clock model (live vs replay) — one abstraction, B1 invariant

The whole architecture rests on a single rule: **the clock master is the flow source,
never a consumer.** `t` is produced by whatever produces the temporal flow; the video and
the thread are two *consumers* of that same `t`, never its source. This unifies live and
replay under one contract and keeps B1 unchanged across both.

| | **Live** | **Replay** |
|---|---|---|
| Source of `t` | the wall (`t = now`, AN broadcasts now) | B2's master clock, advancing at real-time rate |
| Causal feeds | real AN sources (expose only the already-published) | B2 record, gated `wall-clock ≤ t` |
| Video | live HLS (is the present, no scrub) | VOD, slaved to B2's `t` |
| User time commands | **none** — live is read-only, no pause | `play/pause/seek/±Δ/0` to B2 |
| Who knows `t` first | the wall | B2 |

- **B1 is invariant.** It polls causal endpoints that only ever show the past; it never
  receives `t` and cannot tell the wall from B2. The "B1 cannot distinguish replay from live"
  guarantee now extends to time itself.
- **No pause in live.** Live is read-only; the user has no time command. (A local display
  freeze was considered and rejected — it would split the model.)
- **Inside B2, the master clock leads; the video player follows** (see B2). The danger to
  avoid is *two* clocks both believing they are master (B2 advancing `t` *and* a `<video>`
  drifting on its own) — one authority only, clock → video.
- The referential snapshot is **out of this clock entirely** (loaded statically by B1,
  identical in live and replay).

### B4 — `ariane-ui` (mockup interface)

Consumes B1's SSE stream and renders:

- the **clickable thread** building live, each node linking to its canonical record
  (Tribun sheet, amendment, ballot analysis);
- the **video** as an inset / picture-in-picture;
- the **audio waveform** of the track, to make "who is speaking" visible and testable
  (Géraud's explicit ask);
- the **provisional → consolidated** transition shown in place (greyed live text replaced
  by the delayed pass — issue #12).

## Decisions

1. **Separate spec, not a bloat of the product spec.** The parent spec stays the durable
   contract; this one is the mockup architecture.
2. **One canonical thread, two projections.** Do not split the business brick to satisfy
   "two outputs" — split at the output adapter.
3. **Causality enforced in B2, not trusted in B1.** The replayer is the single place that
   gates future data. B1 is written exactly as it would be against the live sources.
4. **Reuse, don't rebuild.** B3 `ariane-capture` (`record_sitting.py`) already captures the
   four live sources with wall-clock stamps and sha1 dedup; the spike already proved live STT
   (Whisper) and diarization (pyannote). The hackathon work is fusion + clock + UI, not R&D (TDC09).
   An internal AN tool ("ttv", author Pierre Drège, demoed by Emmanuel) already covers part of
   the function — **mutualize with it post-hackathon** rather than rebuild (cadrage note 2026-06-29).
5. **Quick-and-dirty stack, but the weaver is real.** B2/B3/B4 may be throwaway; B1 is the
   one piece written to survive into `tricoteuses-ariane`.
6. **The clock master is the flow source, never a consumer** (live: the wall; replay: B2).
   B1 is invariant across live and replay. (Session 2026-06-29.)
7. **Inside B2, the master clock leads; the video player is slaved to it** — not the reverse.
   Slaving four data flows to an approximate, non-monotonic video clock would make the thread
   flicker on decode hiccups.
8. **No pause in live.** Live is read-only; time commands exist only in replay.
9. **Seek backward = purge the thread downstream of `t`** (B1/B4), B2 being stateless w.r.t. `t`.
10. **The referential snapshot is a capture artifact, frozen, not regenerated at demo time.**
    Built by a post-capture resolution pass kept after capture for **causal honesty** (freeze
    a referential contemporary with the sitting), not for any technical reason — resolution is
    a plain HTTP `GET` against the Tricoteuses Parlement REST API (`parlement.tricoteuses.fr`),
    the M2M door, *not* the interactive Moulineuse MCP. The MVP snapshot is the frozen-cache
    form of the prod resolver — same `resolve(uid)` interface, grown with miss→REST API +
    pre-warm later. Nothing thrown away.

## Acceptance criteria (mockup scope)

- [ ] A recorded sitting replays under a shared clock; B1 cannot distinguish replay from live.
- [ ] B2 never serves a source snapshot whose wall-clock is in the demo future (causality).
- [ ] B1 emits `thread.ndjson`; at least one node carries both a canonical actor ID and an
      amendment UID woven from two distinct sources (dérouleur + Eliasse).
- [ ] B1 exposes the thread as an SSE stream **and** as a ttv-compatible compte-rendu JSON.
- [ ] B4 shows the thread building, with video inset and audio waveform, on serenity.
- [ ] At least one node shows a provisional → consolidated replacement.
- [ ] In replay, B2 owns the clock; the video follows `t` (no independent video clock).
- [ ] The UI drives replay by transport commands only (`play/pause/seek`); it never pushes `t`.
- [ ] A backward seek purges the thread downstream of `t` and lets it rebuild.
- [ ] The referential snapshot lives in `record/referential/` and is loaded statically by B1;
      Moulineuse is never called during replay.

## Out of scope (mockup)

- True live hemicycle capture (product phase).
- Facial recognition / biometrics. (Note: the AN gave a green light to build a tribun
  voice-signature base for speaker ID — cadrage note 2026-06-29 — but a persistent voice
  print is biometric data; RGPD clarification pending, so it stays out of the mockup. The
  demo identifies speakers by contextual cues only.)
- Production-grade reconnection, backpressure, auth on the SSE stream.
- The full LLM proofreading pass (#17) — stubbed; one scripted correction is enough to show #12.

## What can be demonstrated *today* (for Xavier Tallon)

Ordered by readiness, given what already exists on serenity:

1. **Causal source replay (ready / near-ready).** Run B3 `ariane-capture` (`record_sitting.py`)
   against a live sitting (or use a past capture) and B2 `ariane-replay` to show the live-available sources
   (dérouleur, Eliasse) revealing themselves on the broadcast clock, with the NVS ground
   truth shown apart for comparison. This alone proves the causality discipline.
2. **The woven thread, sources only (ready).** Even *without* STT wired in, joining the
   Eliasse live pointer (`prochainADiscuter` + `sortEnSeance`) onto the dérouleur trame
   already yields a structured, clickable thread with canonical IDs for a legislative
   sitting — the purest demonstration of issue #10. This is the strongest thing to show
   Xavier first: it is exactly the records-directorate pain (re-keying numbers/outcomes).
3. **STT live overlaid (validated, needs wiring).** Whisper-local utterances on the same
   clock, provisional → consolidated — proven in the spike, to be plugged into B1.
4. **Full B4 UI (to build).** Video inset + waveform + live thread — the demo-day target.

The honest "today" demo is **#1 + #2**: causal replay of the canonical sources weaving a
clickable thread, video aligned. It needs `ariane-replay` (a few hours of glue over existing
captures) and a minimal viewer — no new research.

## Open questions for Emmanuel

To confirm before locking the referential resolution path. **The resolution path moved
from the Moulineuse MCP to the Tricoteuses Parlement REST API** (`parlement.tricoteuses.fr`)
once we established (2026-06-29) that a service cannot depend on an interactive OAuth MCP and
that the REST API answers M2M (plain HTTP, no auth, no Anubis). All three questions below are
about that API.

1. **REST API as the official prod door + its limits.** Is `parlement.tricoteuses.fr` the
   intended machine-to-machine access for a downstream service like Ariane, and is there a
   rate-limit / politeness convention / required UA? **Measured 2026-06-29:** `/acteurs`,
   `/organes`, `/amendements` resolve by exact `?uid[]=` (batched), but the endpoint **400s
   above ~25 `uid[]` per call** — the resolver batches at 20; confirm the real ceiling.
2. **`/documents` filter bug.** On `/documents` the `?uid[]=` filter is **ignored** (returns
   unrelated rows) and `?search=` matches only the title; the working filter is
   `?numNotice=<bibard>&legislature=17`. Is the uid filter meant to work there? (The resolver
   works around it via `numNotice`.)
3. **Referential stability over a week.** Is there a known case where a sitting's actors /
   amendments / documents change between sitting day and a later replay (rectified amendment,
   re-published document)? This is what the week-1 snapshot-vs-current diff will measure, but
   his prior knowledge would tell us whether the freeze is a real safeguard or a formality.

> Two earlier questions are resolved, kept here only as a trail: the **2404-vs-1834 amendment
> count** for text 2915 was an internal mismatch (two SQL filters — 2404 all provenances, 1836
> the AN organe — neither being what the snapshot carries: the resolver pulls only the 702 keys
> the record actually holds), not a question for Emmanuel; and **`organes` in the snapshot** is
> settled — the resolver already pulls the `PO…` groups (12 groups, ~1.5 KB for FIN DE VIE).

## References

- Parent spec: [`2026-06-12-hyperlinked-session-thread-design.md`](2026-06-12-hyperlinked-session-thread-design.md)
- Spike: [`../../spikes/2026-06-23-ttv-streaming-identification/README.md`](../../spikes/2026-06-23-ttv-streaming-identification/README.md)
- B3 `ariane-capture` tooling: `spikes/2026-06-23-ttv-streaming-identification/artifacts/scripts/{record_sitting,record_sources,watch_derouleur_nvs}.py`
- Referential resolution tooling: `spikes/2026-06-23-ttv-streaming-identification/artifacts/scripts/resolve_referential.py` (pure-HTTP, cron-able, resolves a record against `parlement.tricoteuses.fr`)
- Referential resolution (method/keys): [`../data/resolution-referentiels-canutes.md`](../data/resolution-referentiels-canutes.md)
- Issue #10 (weave the thread), #9 (canonical actor ID), #11 (unlisted phases), #12 (provisional vs consolidated), #13 (UI thread + banner)
