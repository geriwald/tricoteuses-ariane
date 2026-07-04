# Ariane — TODO / backlog

Durable backlog: tasks noted mid-session, not yet scheduled or spec'd.

## B1 proofread — LLM inference latency & lag metrics (noted 2026-07-04)

Measure how far behind the live edge the LLM relecture runs, and surface it.

- [ ] **Inference latency** — time each `claude -p` proofread round-trip (wall
      duration of one window's LLM call). Hook: `ProofreadWorker` in
      `b1-weaver/weaver_live.py` around `proofread.claude_cli_transport`.
- [ ] **Lag metric** — delay between an utterance's STT consolidation (its `t` /
      emit time) and the arrival of its llm correction: how stale the relecture
      is versus the live edge. Report per-window and aggregate (p50 / p95).
- [ ] **Expose it** — either a B1 API endpoint (e.g. `GET /metrics`) or timing
      fields on the llm nodes in the ndjson output (e.g. `infer_ms`, `lag_ms`
      added in `correction_nodes`, `b1-weaver/proofread.py`).
