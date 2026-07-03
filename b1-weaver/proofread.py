"""B1 ariane-weaver — LLM proofread pass (spec 2026-07-03-b1-llm-proofread-pass, #17).

Last stage of the B1 rocket: corrects the TEXT of consolidated utterances
(proper nouns, acronyms, STT typos) against the sitting's RESOLVED candidate
list — the same acteurs.json the canonical resolver uses. Speaker attribution
is never touched: it comes from the referential without any LLM.

Contract (D3bis): windows are sent as seq-numbered lists and corrections come
back anchored per seq — the pass never merges or splits utterances, so the
`supersedes` alignment holds by construction. Never invent (D2): a name absent
from the candidates stays as heard, flagged, never "corrected".

Pure core (windowing, prompt, parsing, node generation) + an injectable
transport; the quick-and-dirty `claude -p` call is one isolated function.
A bad LLM response drops its window and never breaks the thread (D5).
"""
import json
import logging
import os
import subprocess

import deduce
import resolve_id

log = logging.getLogger("proofread")

WINDOW_SIZE = 20
WINDOW_OVERLAP = 2
CONTEXT_MARKER = "## Contexte (ne pas corriger)"
TARGETS_MARKER = "## Utterances à relire"
HINTS_MARKER = "## Indices de résolution (calcul déterministe, à confirmer en contexte)"

_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "prompts", "proofread.md")


class ProofreadError(Exception):
    """Invalid LLM output or failed transport — the window is dropped (D5)."""


# ---- windowing (D3) -----------------------------------------------------------

def _is_target(node):
    """Only consolidated STT utterances are proofread; llm nodes never re-enter."""
    return (node.get("kind") == "utterance"
            and node.get("state") == "consolidated"
            and node.get("source") == "stt")


class Windower:
    """Buffers consolidated utterances; emits (context, targets) windows.

    Targets partition the stream — every utterance is proofread exactly once.
    The last `overlap` nodes of a window are re-sent with the next one as
    read-only discourse context (corrections on them are refused downstream)."""

    def __init__(self, size=WINDOW_SIZE, overlap=WINDOW_OVERLAP):
        self._size = size
        self._overlap = overlap
        self._context = []
        self._buffer = []

    def feed(self, node):
        """Buffer one thread node; return (context, targets) when a window fires."""
        if not _is_target(node):
            return None
        self._buffer.append(node)
        if len(self._buffer) < self._size:
            return None
        return self._emit()

    def flush(self):
        """Emit whatever is buffered as a final partial window (timeout / end)."""
        if not self._buffer:
            return None
        return self._emit()

    def _emit(self):
        window = (self._context, self._buffer)
        self._context = self._buffer[-self._overlap:]
        self._buffer = []
        return window


# ---- prompt (D1) ----------------------------------------------------------------

def _load_preamble():
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _render_utterances(nodes):
    return "\n".join(f"[{n['seq']}] {n['text']}" for n in nodes) or "(aucune)"


def resolution_hints(actors, targets):
    """Fuzzy-match hints for the names heard in the window (option D).

    The fuzzy work is done by deterministic, tested code — the same difflib
    resolver the canonical stage uses — and the LLM only confirms in context.
    A «no close candidate» hint reinforces D2: flag, never correct."""
    by_uid = {a["uid"]: a for a in actors}
    hints, seen = [], set()
    for n in targets:
        for heard in deduce.extract_speaker_names(n["text"]):
            if heard in seen:
                continue
            seen.add(heard)
            if not resolve_id._name_tokens(heard):
                continue  # bare title («Madame la Présidente»): nothing to resolve
            r = resolve_id.resolve(heard, actors)
            if r:
                a = by_uid[r["uid"]]
                display = f"{a.get('civ', '')} {a['prenom']} {a['nom']}".strip()
                hints.append(f"«{heard}» → suggestion : {display} "
                             f"(score {r['score']:.2f})")
            else:
                hints.append(f"«{heard}» → aucun candidat proche : "
                             "ne pas corriger, flagger si c'est un nom de personne")
    return hints


def build_prompt(actors, context, targets, preamble=None):
    """Assemble one stateless prompt: instructions + resolved candidates (D1)
    + difflib hints (option D) + read-only context + seq-anchored targets (D3bis)."""
    preamble = preamble if preamble is not None else _load_preamble()
    candidates = "\n".join(
        f"{a.get('civ', '')} {a['prenom']} {a['nom']}".strip() for a in actors)
    hints = "\n".join(resolution_hints(actors, targets)) or "(aucun)"
    return (preamble
            .replace("<<CANDIDATES>>", candidates)
            .replace("<<HINTS>>", f"{HINTS_MARKER}\n{hints}")
            .replace("<<CONTEXT>>", f"{CONTEXT_MARKER}\n{_render_utterances(context)}")
            .replace("<<TARGETS>>", f"{TARGETS_MARKER}\n{_render_utterances(targets)}"))


# ---- parsing (D5 / D3bis) -------------------------------------------------------

def parse_response(raw, allowed_seqs):
    """Validate the LLM reply into [{seq, text, changes, flags}].

    Any deviation — non-JSON, unknown or context-only seq, empty text,
    duplicate seq — raises ProofreadError: the window is dropped, the source
    nodes stand, the thread is never broken."""
    try:
        data = json.loads(raw)
    except ValueError:
        # tolerate a fenced or chatty reply: retry on the outermost {...}
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise ProofreadError("not JSON")
        try:
            data = json.loads(raw[start:end + 1])
        except ValueError:
            raise ProofreadError("not JSON")
    if not isinstance(data, dict) or not isinstance(data.get("corrections"), list):
        raise ProofreadError("missing 'corrections' list")
    out, seen = [], set()
    for item in data["corrections"]:
        if not isinstance(item, dict):
            raise ProofreadError(f"correction is not an object: {item!r}")
        seq, text = item.get("seq"), item.get("text")
        if seq not in allowed_seqs:
            raise ProofreadError(f"seq {seq!r} is not a target of this window")
        if seq in seen:
            raise ProofreadError(f"duplicate correction for seq {seq}")
        if not isinstance(text, str) or not text.strip():
            raise ProofreadError(f"empty text for seq {seq}")
        seen.add(seq)
        out.append({"seq": seq, "text": text,
                    "changes": list(item.get("changes") or []),
                    "flags": list(item.get("flags") or [])})
    return out


# ---- node generation ------------------------------------------------------------

def correction_nodes(corrections, by_seq, seq):
    """Corrections → supersedes nodes (+ reported flags).

    A text change becomes an `utterance` node, `source: "llm"`, superseding the
    source node and inheriting its `t`. Flag-only items (doubt, unknown name)
    are reported but emit nothing: never invent (D2), never pollute the thread."""
    nodes, flags = [], []
    for c in corrections:
        src = by_seq[c["seq"]]
        if c["flags"]:
            flags.append({"seq": c["seq"], "flags": c["flags"]})
        if c["text"] != src["text"]:
            nodes.append({"t": src["t"], "seq": seq.next(), "kind": "utterance",
                          "state": "consolidated", "text": c["text"],
                          "source": "llm", "supersedes": src["seq"]})
    return nodes, flags


# ---- orchestration ---------------------------------------------------------------

class Proofreader:
    """feed(node) → corrected nodes when a window fires (else []).

    The transport is injected (mocked in tests, `claude_cli_transport` live).
    Every failure mode — transport crash, garbage output — drops the window
    and leaves the proofreader ready for the next one (D5)."""

    def __init__(self, actors, transport, seq,
                 size=WINDOW_SIZE, overlap=WINDOW_OVERLAP, preamble=None):
        self._actors = actors
        self._transport = transport
        self._seq = seq
        self._preamble = preamble if preamble is not None else _load_preamble()
        self._windower = Windower(size=size, overlap=overlap)
        self.flags = []  # [{seq, flags}] — doubts reported by the model (D2)

    def feed(self, node):
        window = self._windower.feed(node)
        return self._run(window) if window else []

    def flush(self):
        window = self._windower.flush()
        return self._run(window) if window else []

    def _run(self, window):
        context, targets = window
        try:
            prompt = build_prompt(self._actors, context, targets,
                                  preamble=self._preamble)
            raw = self._transport(prompt)
            corrections = parse_response(raw, {n["seq"] for n in targets})
        except Exception as e:  # noqa: BLE001 — a proofread stage must never crash B1
            log.warning("window dropped (%d utterances): %s", len(targets), e)
            return []
        nodes, flags = correction_nodes(
            corrections, {n["seq"]: n for n in targets}, self._seq)
        for f in flags:
            log.info("flagged seq %s: %s", f["seq"], "; ".join(f["flags"]))
        self.flags.extend(flags)
        return nodes


# ---- transport (quick and dirty, spec D4/D6) --------------------------------------

def claude_cli_transport(prompt, model="sonnet", timeout=180):
    """One isolated `claude -p` call on the local CLI (subscription, caladan).

    Deliberately throwaway: the D5 contract keeps it swappable for the API."""
    res = subprocess.run(["claude", "-p", "--model", model],
                         input=prompt, capture_output=True, text=True,
                         timeout=timeout)
    if res.returncode != 0:
        raise ProofreadError(f"claude CLI exited {res.returncode}: {res.stderr[:200]}")
    return res.stdout


# ---- batch runner (acceptance run on a captured thread) ---------------------------

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Proofread a captured thread.ndjson (batch acceptance run).")
    parser.add_argument("--thread", required=True, help="thread.ndjson to proofread")
    parser.add_argument("--actors", required=True, help="referential/acteurs.json")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--limit", type=int, default=None,
                        help="only feed the first N consolidated utterances")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with open(args.actors, encoding="utf-8") as f:
        actors = json.load(f)
    nodes = [json.loads(line) for line in open(args.thread, encoding="utf-8")
             if line.strip()]

    import weaver as w
    seq = w.Seq()
    seq._n = max((n["seq"] for n in nodes), default=-1) + 1  # append after the log

    def transport(prompt):
        return claude_cli_transport(prompt, model=args.model)

    pr = Proofreader(actors, transport, seq)
    fed = 0
    for node in nodes:
        if args.limit is not None and fed >= args.limit:
            break
        fed += _is_target(node)
        for out in pr.feed(node):
            print(json.dumps(out, ensure_ascii=False))
    for out in pr.flush():
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
