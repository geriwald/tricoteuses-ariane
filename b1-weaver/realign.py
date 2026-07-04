"""Paragraph→seq re-aligner for the LLM proofread pass (spec 2026-07-03, D8).

The proofreader sends a window as one flowing paragraph and gets a corrected,
re-segmented transcript back (one utterance per line). This module maps each
corrected segment onto the original seqs it covers, so a merged node can
supersede several STT fragments at once — fixing the choppy mid-sentence
segmentation the STT produces (and repairing names split across a boundary).

Method: word-diff the original concatenation against the corrected text; each
corrected word inherits the original seq it aligned to. Lines that share an
original seq are unioned into one segment (a seq's audio can't be cut in two),
so re-segmentation is lossless. Two guards: a seq the model deleted outright
(no surviving word) is left as its original node rather than folded away
(content preservation); a corrected line covering no original word (pure
invention) is dropped.
"""
from collections import defaultdict
from difflib import SequenceMatcher


def _find(parent, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent, a, b):
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[max(ra, rb)] = min(ra, rb)


def realign(nodes, corrected_text):
    """Map a corrected, re-segmented paragraph back onto the window's seqs.

    Returns [{seqs: [...], text: str}] for the segments that changed or merged
    fragments, in reading order. `nodes` are the window's target utterances
    ({seq, text}) in order; `corrected_text` is the LLM's corrected transcript,
    one utterance per line."""
    orig_words, orig_seq = [], []
    for n in nodes:
        for w in n["text"].split():
            orig_words.append(w)
            orig_seq.append(n["seq"])

    lines = [ln.strip() for ln in corrected_text.splitlines() if ln.strip()]
    corr_words, corr_line = [], []
    for li, ln in enumerate(lines):
        for w in ln.split():
            corr_words.append(w)
            corr_line.append(li)
    if not lines:
        return []

    # seq -> set of corrected lines its surviving words landed on. Only equal/
    # replace count as survival; a pure deletion leaves no membership, so a
    # fully-deleted seq stays its original node (content preservation).
    seq_lines = defaultdict(set)
    for tag, i1, i2, j1, j2 in SequenceMatcher(
            None, orig_words, corr_words).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                seq_lines[orig_seq[i1 + k]].add(corr_line[j1 + k])
        elif tag == "replace":
            span = i2 - i1
            for m in range(j2 - j1):
                seq = orig_seq[i1 + (m * span) // (j2 - j1)]
                seq_lines[seq].add(corr_line[j1 + m])
        # delete: words vanished, no membership recorded
        # insert: corrected words own no seq (already part of their line's text)

    # union lines that share a seq — a seq spanning two lines rejoins them,
    # keeping re-segmentation lossless
    parent = list(range(len(lines)))
    for ls in seq_lines.values():
        ls = sorted(ls)
        for other in ls[1:]:
            _union(parent, ls[0], other)

    comp_lines = defaultdict(list)
    for li in range(len(lines)):
        comp_lines[_find(parent, li)].append(li)
    comp_seqs = defaultdict(set)
    for seq, ls in seq_lines.items():
        comp_seqs[_find(parent, min(ls))].add(seq)

    by_text = {n["seq"]: n["text"] for n in nodes}
    out = []
    for root in sorted(comp_lines):
        seqs = sorted(comp_seqs.get(root, set()))
        if not seqs:
            continue                                  # invented line, no coverage
        text = " ".join(lines[li] for li in comp_lines[root])
        if len(seqs) == 1 and text == by_text[seqs[0]]:
            continue                                  # unchanged single utterance
        out.append({"seqs": seqs, "text": text})
    return out
