"""Tests for the B1 LLM proofread pass (spec 2026-07-03-b1-llm-proofread-pass, #17).

The pass corrects the TEXT of consolidated utterances (proper nouns, acronyms)
against the sitting's resolved candidate list — never the speaker attribution,
which comes from the referential without any LLM. Fixtures reuse real STT noise
from the 26/06 sitting («Bruet» for GRUET) and the spike («Someni» for Somaini).

The CLI transport is injected and mocked here; the real call is exercised once
manually (acceptance run documented in the spec).
"""
import json

import pytest

import proofread
import weaver as w

ACTORS = [
    {"uid": "PA1001", "civ": "M.", "prenom": "Thibault", "nom": "Bazin"},
    {"uid": "PA1002", "civ": "Mme", "prenom": "Justine", "nom": "Gruet"},
    {"uid": "PA1003", "civ": "M.", "prenom": "Philippe", "nom": "Juvin"},
]


def utt(seq, text, t=None, state="consolidated", source="stt"):
    return {"t": t if t is not None else seq * 1000, "seq": seq,
            "kind": "utterance", "state": state, "text": text, "source": source}


# ---- windowing (D3 / D3bis) ---------------------------------------------------

def test_window_fires_at_size_with_context_carry():
    win = proofread.Windower(size=3, overlap=2)
    out = [win.feed(utt(i, f"u{i}")) for i in range(3)]
    assert out[0] is None and out[1] is None
    ctx, targets = out[2]
    assert ctx == []                                # first window: no context yet
    assert [n["seq"] for n in targets] == [0, 1, 2]
    # next window: last `overlap` nodes carried as context, NOT as targets
    for i in (3, 4):
        assert win.feed(utt(i, f"u{i}")) is None
    ctx, targets = win.feed(utt(5, "u5"))
    assert [n["seq"] for n in ctx] == [1, 2]
    assert [n["seq"] for n in targets] == [3, 4, 5]  # targets partition the stream


def test_window_ignores_interim_other_kinds_and_llm_nodes():
    win = proofread.Windower(size=2, overlap=1)
    assert win.feed(utt(0, "brouillon", state="provisional")) is None
    assert win.feed({"t": 0, "seq": 1, "kind": "amendment", "state": "consolidated",
                     "source": "stt"}) is None
    assert win.feed(utt(2, "déjà corrigé", source="llm")) is None
    assert win.feed(utt(3, "a")) is None
    ctx, targets = win.feed(utt(4, "b"))
    assert [n["seq"] for n in targets] == [3, 4]


def test_flush_emits_partial_window_once():
    win = proofread.Windower(size=10, overlap=2)
    win.feed(utt(0, "a"))
    win.feed(utt(1, "b"))
    ctx, targets = win.flush()
    assert [n["seq"] for n in targets] == [0, 1]
    assert win.flush() is None                      # nothing buffered → nothing


# ---- prompt (D1) ----------------------------------------------------------------

def test_prompt_carries_candidates_targets_and_separated_context():
    ctx = [utt(7, "contexte antérieur")]
    targets = [utt(8, "madame Bruet a la parole")]
    p = proofread.build_prompt(ACTORS, ctx, targets)
    assert "Mme Justine Gruet" in p                 # resolved candidate list (D1)
    assert "[8] madame Bruet a la parole" in p      # seq-anchored target (D3bis)
    assert "[7] contexte antérieur" in p
    # context precedes targets and sits under its own marker so the parser can
    # refuse corrections on it
    assert p.index("[7]") < p.index("[8]")
    assert proofread.CONTEXT_MARKER in p


# ---- parsing (D5 / D3bis) -----------------------------------------------------

def _resp(corrections):
    return json.dumps({"corrections": corrections})


def test_parse_accepts_valid_corrections_and_code_fences():
    raw = "```json\n" + _resp([{"seq": 8, "text": "Madame Gruet a la parole",
                                "changes": ["Bruet→Gruet"], "flags": []}]) + "\n```"
    out = proofread.parse_response(raw, allowed_seqs={8})
    assert out == [{"seq": 8, "text": "Madame Gruet a la parole",
                    "changes": ["Bruet→Gruet"], "flags": []}]


@pytest.mark.parametrize("raw", [
    "pas du json",
    _resp([{"seq": 99, "text": "seq inconnu"}]),          # unknown seq
    _resp([{"seq": 7, "text": "correction du contexte"}]),  # context-only seq
    _resp([{"seq": 8, "text": ""}]),                      # empty text
    _resp([{"seq": 8, "text": "a"}, {"seq": 8, "text": "b"}]),  # duplicate seq
    json.dumps({"autre": []}),                            # missing key
])
def test_parse_rejects_invalid_output(raw):
    with pytest.raises(proofread.ProofreadError):
        proofread.parse_response(raw, allowed_seqs={8})


# ---- node generation (supersedes) ----------------------------------------------

def test_correction_becomes_supersedes_node_inheriting_t():
    seq = w.Seq()
    seq.next()  # thread already has node 0
    src = utt(0, "madame Bruet a la parole", t=42_000)
    nodes, flags = proofread.correction_nodes(
        [{"seq": 0, "text": "madame Gruet a la parole", "changes": ["Bruet→Gruet"],
          "flags": []}], {0: src}, seq)
    assert len(nodes) == 1
    n = nodes[0]
    assert n["kind"] == "utterance" and n["state"] == "consolidated"
    assert n["source"] == "llm" and n["supersedes"] == 0
    assert n["t"] == 42_000 and n["seq"] == 1
    assert n["text"] == "madame Gruet a la parole"
    assert flags == []


def test_identical_text_yields_no_node_and_flag_only_is_reported_not_emitted():
    seq = w.Seq()
    src = utt(0, "monsieur Someni, peut-être")
    nodes, flags = proofread.correction_nodes(
        [{"seq": 0, "text": "monsieur Someni, peut-être", "changes": [],
          "flags": ["nom inconnu des candidats: Someni"]}], {0: src}, seq)
    assert nodes == []                              # never invent (D2): no rewrite
    assert flags == [{"seq": 0, "flags": ["nom inconnu des candidats: Someni"]}]


# ---- orchestration (transport injecté, D5: never break the thread) -------------

def make_proofreader(transport, size=2, overlap=1):
    return proofread.Proofreader(ACTORS, transport, seq=w.Seq(),
                                 size=size, overlap=overlap)


def test_end_to_end_correction_with_fake_transport():
    def transport(prompt):
        assert "Mme Justine Gruet" in prompt
        return _resp([{"seq": 1, "text": "L'amendement 449, madame Gruet, défendu",
                       "changes": ["Bruet→Gruet"], "flags": []}])
    pr = make_proofreader(transport)
    assert pr.feed(utt(0, "Le scrutin est ouvert.")) == []
    out = pr.feed(utt(1, "L'amendement 449, madame Bruet, défendu"))
    assert len(out) == 1
    assert out[0]["text"] == "L'amendement 449, madame Gruet, défendu"
    assert out[0]["supersedes"] == 1 and out[0]["source"] == "llm"


@pytest.mark.parametrize("transport", [
    lambda p: (_ for _ in ()).throw(RuntimeError("cli down")),  # transport crash
    lambda p: "je ne suis pas du JSON",                          # garbage output
])
def test_bad_transport_never_breaks_the_thread(transport):
    pr = make_proofreader(transport)
    pr.feed(utt(0, "a"))
    assert pr.feed(utt(1, "b")) == []               # window dropped, thread intact
    # the proofreader stays functional for the next window
    pr.feed(utt(2, "c"))


def test_flush_runs_the_last_partial_window():
    calls = []
    def transport(prompt):
        calls.append(prompt)
        return _resp([])
    pr = make_proofreader(transport, size=10)
    pr.feed(utt(0, "fin de séance"))
    assert pr.flush() == []
    assert len(calls) == 1 and "[0] fin de séance" in calls[0]


# ---- resolution hints (option D: deterministic difflib, LLM confirms in context)

def test_resolution_hints_fuzzy_unknown_title_and_silence():
    targets = [utt(0, "L'amendement 449, madame Bruet, défendu"),
               utt(1, "je rejoins monsieur Someni sur ce point"),
               utt(2, "Merci Madame la Présidente."),   # title-only: no hint
               utt(3, "Le scrutin est ouvert.")]        # no name: no hint
    hints = proofread.resolution_hints(ACTORS, targets)
    assert len(hints) == 2
    assert any("madame Bruet" in h and "Justine Gruet" in h for h in hints)
    assert any("Someni" in h and "aucun candidat proche" in h for h in hints)


def test_resolution_hints_dedupe_repeated_names():
    targets = [utt(0, "madame Bruet, défendu"), utt(1, "merci madame Bruet")]
    assert len(proofread.resolution_hints(ACTORS, targets)) == 1


def test_prompt_carries_hints_section():
    targets = [utt(8, "madame Bruet a la parole")]
    p = proofread.build_prompt(ACTORS, [], targets)
    assert proofread.HINTS_MARKER in p
    assert "«madame Bruet»" in p          # the computed hint line, not just the list
