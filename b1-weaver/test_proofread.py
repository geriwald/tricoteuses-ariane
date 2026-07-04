"""Tests for the B1 LLM proofread pass (spec 2026-07-03-b1-llm-proofread-pass, #17).

Paragraph + re-segmentation contract (D7/D8): the window is sent as one flowing
paragraph and the LLM returns a corrected transcript, one utterance per line,
free to merge STT fragments. `realign` (tested in test_realign.py) maps segments
back to the seqs they cover. These tests cover windowing, prompt assembly, the
plain-text+NOTES parsing, multi-seq node generation, and the
never-break-the-thread orchestration. The CLI transport is injected and mocked.
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


# ---- windowing (D3) -----------------------------------------------------------

def test_window_fires_at_size_with_context_carry():
    win = proofread.Windower(size=3, overlap=2)
    out = [win.feed(utt(i, f"u{i}")) for i in range(3)]
    assert out[0] is None and out[1] is None
    ctx, targets = out[2]
    assert ctx == []
    assert [n["seq"] for n in targets] == [0, 1, 2]
    for i in (3, 4):
        assert win.feed(utt(i, f"u{i}")) is None
    ctx, targets = win.feed(utt(5, "u5"))
    assert [n["seq"] for n in ctx] == [1, 2]
    assert [n["seq"] for n in targets] == [3, 4, 5]


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
    assert win.flush() is None


# ---- prompt (D1) --------------------------------------------------------------

def test_prompt_paragraph_mode_carries_candidates_hints_and_prose():
    ctx = [utt(7, "contexte antérieur")]
    targets = [utt(8, "L'amendement 449, madame Bruet, défendu")]
    p = proofread.build_prompt(ACTORS, ctx, targets)
    assert "Mme Justine Gruet" in p
    assert "L'amendement 449, madame Bruet, défendu" in p
    assert "contexte antérieur" in p
    assert "[8]" not in p and "[7]" not in p
    assert proofread.HINTS_MARKER in p


def test_prompt_carries_difflib_hint_line():
    targets = [utt(8, "madame Bruet a la parole")]
    p = proofread.build_prompt(ACTORS, [], targets)
    assert "«madame Bruet»" in p and "Justine Gruet" in p


# ---- parsing (D5): plain paragraph + NOTES ------------------------------------

def test_parse_corrected_plain_paragraph():
    assert proofread.parse_corrected("Le texte corrigé.") == ("Le texte corrigé.", [])


def test_parse_corrected_strips_notes_section():
    raw = "Le texte corrigé.\nNOTES :\n- «Someni» inconnu, laissé tel quel\n- doute sur 62"
    text, flags = proofread.parse_corrected(raw)
    assert text == "Le texte corrigé."
    assert flags == ["«Someni» inconnu, laissé tel quel", "doute sur 62"]


def test_parse_corrected_tolerates_code_fence():
    text, _ = proofread.parse_corrected("```\nLe texte.\n```")
    assert text == "Le texte."


def test_parse_corrected_rejects_empty():
    with pytest.raises(proofread.ProofreadError):
        proofread.parse_corrected("   ")


# ---- node generation (multi-seq supersedes over realign output) ----------------

def test_single_seq_correction_node():
    seq = w.Seq()
    seq.next()  # thread already has node 0
    src = utt(0, "madame Bruet a la parole", t=42_000)
    nodes = proofread.correction_nodes(
        [{"seqs": [0], "text": "madame Gruet a la parole"}], {0: src}, seq)
    assert len(nodes) == 1
    n = nodes[0]
    assert n["kind"] == "utterance" and n["state"] == "consolidated"
    assert n["source"] == "llm" and n["supersedes"] == 0   # single int, not list
    assert n["t"] == 42_000 and n["seq"] == 1
    assert n["text"] == "madame Gruet a la parole"


def test_merged_node_supersedes_list_and_inherits_earliest_t():
    seq = w.Seq()
    by_seq = {0: utt(0, "Le 1357, Madame Lou", t=90_000),
              1: utt(1, "boucher a la parole", t=92_000)}
    nodes = proofread.correction_nodes(
        [{"seqs": [0, 1], "text": "Le 1357, Madame Leboucher a la parole."}],
        by_seq, seq)
    assert len(nodes) == 1
    n = nodes[0]
    assert n["supersedes"] == [0, 1]                       # merged → list
    assert n["t"] == 90_000                                # earliest of the two
    assert n["text"] == "Le 1357, Madame Leboucher a la parole."


# ---- resolution hints (option D) ----------------------------------------------

def test_resolution_hints_fuzzy_unknown_title_and_silence():
    targets = [utt(0, "L'amendement 449, madame Bruet, défendu"),
               utt(1, "je rejoins monsieur Someni sur ce point"),
               utt(2, "Merci Madame la Présidente."),
               utt(3, "Le scrutin est ouvert.")]
    hints = proofread.resolution_hints(ACTORS, targets)
    assert len(hints) == 2
    assert any("madame Bruet" in h and "Justine Gruet" in h for h in hints)
    assert any("Someni" in h and "aucun candidat proche" in h for h in hints)


def test_resolution_hints_dedupe_repeated_names():
    targets = [utt(0, "madame Bruet, défendu"), utt(1, "merci madame Bruet")]
    assert len(proofread.resolution_hints(ACTORS, targets)) == 1


# ---- orchestration (paragraph transport, D5: never break the thread) -----------

def make_proofreader(transport, size=2, overlap=1):
    return proofread.Proofreader(ACTORS, transport, seq=w.Seq(),
                                 size=size, overlap=overlap)


def test_end_to_end_correction_and_merge():
    def transport(prompt):
        assert "Mme Justine Gruet" in prompt
        # the model rejoins the split fragments and fixes the name, one line
        return "Le scrutin est ouvert. L'amendement 449, madame Gruet, défendu."
    pr = make_proofreader(transport)
    assert pr.feed(utt(0, "Le scrutin est ouvert. L'amendement 449, madame Bruet,")) == []
    out = pr.feed(utt(1, "défendu."))
    assert len(out) == 1
    assert out[0]["text"] == "Le scrutin est ouvert. L'amendement 449, madame Gruet, défendu."
    assert out[0]["supersedes"] == [0, 1] and out[0]["source"] == "llm"


def test_notes_are_reported_and_do_not_leak_into_the_text():
    def transport(prompt):
        return ("Je rejoins monsieur Someni sur ce point. Le vote est acquis.\n"
                "NOTES :\n- «Someni» absent des candidats, laissé tel quel")
    pr = make_proofreader(transport)
    pr.feed(utt(0, "Je rejoins monsieur Someni sur ce point. Le vote est acquis."))
    out = pr.feed(utt(1, "Le vote est acquis."))
    # the corrected text equals the concatenation → the merge covers 0+1
    assert pr.flags == ["«Someni» absent des candidats, laissé tel quel"]


@pytest.mark.parametrize("transport", [
    lambda p: (_ for _ in ()).throw(RuntimeError("cli down")),
    lambda p: "",
])
def test_bad_transport_never_breaks_the_thread(transport):
    pr = make_proofreader(transport)
    pr.feed(utt(0, "a"))
    assert pr.feed(utt(1, "b")) == []
    pr.feed(utt(2, "c"))


def test_flush_runs_the_last_partial_window():
    calls = []
    def transport(prompt):
        calls.append(prompt)
        return "fin de séance"
    pr = make_proofreader(transport, size=10)
    pr.feed(utt(0, "fin de séance"))
    assert pr.flush() == []
    assert len(calls) == 1 and "fin de séance" in calls[0]
