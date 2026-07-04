"""Tests for the paragraph→seq re-aligner v2 (spec D8: re-segmentation allowed).

The LLM returns the corrected transcript, one utterance per line, free to MERGE
STT fragments that were split mid-sentence. realign() word-diffs the original
against the corrected text and returns, per corrected segment, the set of
original seqs it covers — so a merged node can supersede several seqs. It never
drops content: a seq the model deleted outright is left as its original node
rather than folded away.
"""
import realign


def nodes(*pairs):
    return [{"seq": s, "text": t} for s, t in pairs]


def test_single_in_seq_substitution_covers_one_seq():
    orig = nodes((0, "Le scrutin est ouvert."),
                 (1, "L'amendement 449, madame Bruet, défendu."))
    corrected = "Le scrutin est ouvert.\nL'amendement 449, madame Gruet, défendu."
    out = realign.realign(orig, corrected)
    assert out == [{"seqs": [1], "text": "L'amendement 449, madame Gruet, défendu."}]


def test_unchanged_paragraph_yields_no_corrections():
    orig = nodes((0, "Je vous remercie."), (1, "La parole est à la ministre."))
    out = realign.realign(orig, "Je vous remercie.\nLa parole est à la ministre.")
    assert out == []


def test_merge_of_mid_sentence_fragments_supersedes_both_seqs():
    orig = nodes((0, "je suis saisie d'une demande"),
                 (1, "que je fais annoncer"))
    corrected = "je suis saisie d'une demande que je fais annoncer"
    out = realign.realign(orig, corrected)
    assert out == [{"seqs": [0, 1],
                    "text": "je suis saisie d'une demande que je fais annoncer"}]


def test_merge_plus_correction_across_a_boundary():
    orig = nodes((0, "Le 1357, Madame Lou"), (1, "boucher a la parole"))
    corrected = "Le 1357, Madame Leboucher a la parole."
    out = realign.realign(orig, corrected)
    assert out == [{"seqs": [0, 1], "text": "Le 1357, Madame Leboucher a la parole."}]


def test_only_changed_or_merged_segments_are_emitted():
    orig = nodes((0, "un"), (1, "deux"), (2, "troie"), (3, "quatre"))
    corrected = "un\ndeux\ntrois\nquatre"
    out = realign.realign(orig, corrected)
    assert out == [{"seqs": [2], "text": "trois"}]


def test_deleted_seq_is_left_untouched_not_folded_away():
    orig = nodes((0, "propos liminaire à couper"), (1, "le vote est acquis"))
    out = realign.realign(orig, "le vote est acquis")
    assert out == []                       # seq 0 not superseded, seq 1 unchanged


def test_split_of_one_seq_across_lines_stays_lossless():
    # the model splits one utterance across two lines (with a change on the last
    # word); they rejoin — a seq's audio can't be cut, and no word is lost.
    orig = nodes((0, "a b c d"))
    out = realign.realign(orig, "a b\nc D")
    assert out == [{"seqs": [0], "text": "a b c D"}]


def test_hallucinated_standalone_line_is_ignored():
    orig = nodes((0, "le vote est acquis"))
    out = realign.realign(orig, "le vote est acquis\nJe vous remercie infiniment.")
    assert out == []
