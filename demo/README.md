# Ariane demo (causal replay mockup)

Quick-and-dirty mockup of issue #10 ("weave the thread") via **causal replay**.
See the architecture spec: [`../docs/specs/2026-06-26-hackathon-mockup-architecture-design.md`](../docs/specs/2026-06-26-hackathon-mockup-architecture-design.md).

## The data model (corrected 2026-06-26)

The weave joins **live-available, machine-generated, speaker-less** sources only:

- **dérouleur = structural trame.** The ordered list of amendments/articles, each line
  carrying canonical IDs (`uid` Eliasse, `author_tribun`). It gives the skeleton and the
  IDs, **not the live position** — the highlighted block is a growing section, not a cursor
  (measured 2026-06-25).
- **Eliasse `prochainADiscuter` = live position pointer.** Which amendment is up now
  (`numAmdt`) + its outcome (`sort`). Joined onto the dérouleur trame by amendment number to
  resolve canonical IDs and the registered author.
- **NVS = ground truth, NOT an input.** It names speakers → a human keyed it in régie →
  that is exactly what Ariane automates, so it is an *output to compare against*, never an
  input. Shown in the UI in a fenced "not available live, validation only" pane.

## Status

- [x] `fixtures/sample-legislative/index.ndjson` — replayable fixture (synthetic: **real
      shape, illustrative values**), one record per tick with a wall-clock stamp. The same
      shape `record_sources.py` produces, extended so `derouleur` carries the trame list
      (the recorder should be updated to emit it from `racine.contenu.phase[].ligne[]`).
- [ ] `server.py` — causal replayer + weaver + SSE (forthcoming).
- [ ] `index.html` — clickable thread + video inset + waveform + NVS ground-truth pane.

## Fixture format

```
{ "wall": "<iso>",                       # wall-clock of this snapshot (causality key)
  "derouleur": { "phase", "place",
                 "trame": [ {num, uid, author_tribun, label}, ... ] },  # stable structure + IDs
  "eliasse":   { "numAmdt", "sort", "etat", "place" },                  # live pointer + outcome
  "nvs":       { "last_label", "last_type", "last_speaker", "last_tribun" } }  # ground truth
```

The replayer serves each snapshot only when its `wall` ≤ the demo clock (causality); the
weaver emits a thread node when `eliasse.numAmdt` changes (amendment called → join trame for
IDs) or `eliasse.sort` falls (outcome). The NVS is streamed **unfiltered** to the UI pane.
