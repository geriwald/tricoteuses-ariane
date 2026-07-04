"""B1 ariane-weaver — LLM proofread pass (spec 2026-07-03-b1-llm-proofread-pass, #17).

Last stage of the B1 rocket: corrects the TEXT of consolidated utterances
(proper nouns, acronyms, STT typos) against the sitting's RESOLVED candidate
list — the same acteurs.json the canonical resolver uses. Speaker attribution
is never touched: it comes from the referential without any LLM.

Paragraph contract (spec D7/D8): the window is sent as ONE flowing paragraph —
the LLM reads real prose and catches far more than it did on numbered `[seq]`
fragments — and returns a corrected transcript, one utterance per line, free to
merge STT fragments split mid-sentence. `realign` word-diffs original against
corrected and reports which original seqs each corrected segment covers, so a
node may supersede SEVERAL seqs at once (`supersedes` is then a list). Never
invent (D2): a name absent from the candidates is flagged in NOTES, never
rewritten; a seq the model drops outright is left untouched, not folded away.
A transport failure or empty reply drops the window, never the thread (D5).

Pure core (windowing, prompt, parsing, realign, node generation) + an injectable
transport; the quick-and-dirty `claude -p` call is one isolated function.
"""
import json
import logging
import os
import re
import subprocess

import deduce
import realign
import resolve_id

log = logging.getLogger("proofread")

WINDOW_SIZE = 20
WINDOW_OVERLAP = 2
HINTS_MARKER = "## Indices de résolution (calcul déterministe, à confirmer en contexte)"
_NOTES_RE = re.compile(r"\n\s*NOTES?\s*:\s*\n?", re.I)

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
    The last `overlap` nodes of a window are re-shown with the next one as
    read-only discourse context (the model is told not to re-emit them)."""

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
        self._context = self._buffer[-self._overlap:] if self._overlap else []
        self._buffer = []
        return window


# ---- prompt (D1) ----------------------------------------------------------------

def _load_preamble():
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


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
                             "ne pas corriger, signaler si c'est un nom de personne")
    return hints


def build_prompt(actors, context, targets, preamble=None):
    """Assemble one stateless prompt: instructions + resolved candidates (D1)
    + difflib hints (option D) + read-only context + the target paragraph."""
    preamble = preamble if preamble is not None else _load_preamble()
    candidates = "\n".join(
        f"{a.get('civ', '')} {a['prenom']} {a['nom']}".strip() for a in actors)
    hints = "\n".join(resolution_hints(actors, targets)) or "(aucun)"
    context_text = " ".join(n["text"] for n in context) or "(début de séance)"
    target_text = " ".join(n["text"] for n in targets)
    return (preamble
            .replace("<<CANDIDATES>>", candidates)
            .replace("<<HINTS>>", f"{HINTS_MARKER}\n{hints}")
            .replace("<<CONTEXT>>", context_text)
            .replace("<<TARGET>>", target_text))


# ---- parsing (D5): plain corrected transcript + optional NOTES flags -----------

def parse_corrected(raw):
    """Split the LLM reply into (corrected_text, flags).

    Robust by design: any non-empty text is a valid corrected transcript — there
    is no per-seq structure to break. A trailing «NOTES:» section carries the
    model's doubts (never invent). An empty reply raises so the window drops."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    flags = []
    m = _NOTES_RE.search(text)
    if m:
        notes = text[m.end():]
        text = text[:m.start()].strip()
        flags = [ln.strip(" -•\t") for ln in notes.splitlines() if ln.strip()]
    if not text.strip():
        raise ProofreadError("empty corrected paragraph")
    return text.strip(), flags


# ---- node generation ------------------------------------------------------------

def correction_nodes(realigned, by_seq, seq):
    """Realigned segments → supersedes nodes.

    Each becomes an `utterance` node, `source: "llm"`. It supersedes the seq(s)
    it covers — a single int when one, a list when it merged fragments — and
    inherits the earliest `t` of those seqs (the utterance's start on the video).
    `realign` has already dropped unchanged and uncovered segments."""
    nodes = []
    for c in realigned:
        seqs = c["seqs"]
        supersedes = seqs[0] if len(seqs) == 1 else list(seqs)
        nodes.append({"t": min(by_seq[s]["t"] for s in seqs), "seq": seq.next(),
                      "kind": "utterance", "state": "consolidated",
                      "text": c["text"], "source": "llm", "supersedes": supersedes})
    return nodes


# ---- orchestration ---------------------------------------------------------------

class Proofreader:
    """feed(node) → corrected nodes when a window fires (else []).

    The transport is injected (mocked in tests, `claude_cli_transport` live).
    Every failure mode — transport crash, empty output — drops the window and
    leaves the proofreader ready for the next one (D5)."""

    def __init__(self, actors, transport, seq,
                 size=WINDOW_SIZE, overlap=WINDOW_OVERLAP, preamble=None):
        self._actors = actors
        self._transport = transport
        self._seq = seq
        self._preamble = preamble if preamble is not None else _load_preamble()
        self._windower = Windower(size=size, overlap=overlap)
        self.flags = []  # notes reported by the model (never invent, D2)

    def set_actors(self, actors):
        """Refresh the candidate list live (a sitting switch swaps the actors)."""
        self._actors = actors

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
            corrected, flags = parse_corrected(raw)
        except Exception as e:  # noqa: BLE001 — a proofread stage must never crash B1
            log.warning("window dropped (%d utterances): %s", len(targets), e)
            return []
        realigned = realign.realign(targets, corrected)
        for f in flags:
            log.info("note: %s", f)
        self.flags.extend(flags)
        return correction_nodes(realigned, {n["seq"]: n for n in targets}, self._seq)


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
