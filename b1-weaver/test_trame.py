"""Tests for B1 trame weaving (spec 2026-07-02-b1-trame-weaving-design).

The trame core is pure: TrameWeaver.feed_snapshot(derouleur_snapshot, t_ms)
returns thread nodes for every line *entering* the régie highlight
(ligne_video_highlighted="true"). Nodes are consolidated at birth (the trame is
a régie source, not a hypothesis); an in-place label enrichment supersedes the
line's previous node. `seq` is shared with the STT Weaver so both interleave
into one strictly-increasing sequence.
"""
import glob
import json
import os

import pytest

import trame
import weaver as w

BUNDLE = "/mnt/data/ariane-capture/2026-06-26-evening"


def snapshot(*lignes, phase_extra=None):
    """A minimal derouleur snapshot with one phase carrying the given lines."""
    phase = {"phase_libelle": "TEST", "phase_type": "DA", "ligne": list(lignes)}
    if phase_extra:
        phase.update(phase_extra)
    return {"racine": {"contenu": {"phase": [phase]}}}


def adt(id="1", libelle="Adt n° 1388 de M. BOVET", tribun="793182",
        uid="AMANR5L17PO838901BTC2915P0D1N001388", highlighted=True, **extra):
    ligne = {"id": id, "ligne_type": "ADT", "ligne_libelle_1": libelle,
             "depute_tribun_id": tribun, "ligne_amendement_uid": uid, **extra}
    if highlighted:
        ligne["ligne_video_highlighted"] = "true"
    return ligne


def test_entry_emits_consolidated_node_with_canonical():
    tw = trame.TrameWeaver()
    (node,) = tw.feed_snapshot(snapshot(adt()), t_ms=42000)

    assert node["kind"] == "amendment"
    assert node["state"] == "consolidated"
    assert node["source"] == "derouleur"
    assert node["t"] == 42000
    assert node["text"] == "Adt n° 1388 de M. BOVET"
    assert node["canonical"]["acteur"] == "PA793182"
    assert node["canonical"]["tribun"] == "793182"
    assert node["canonical"]["amendement_uid"] == "AMANR5L17PO838901BTC2915P0D1N001388"
    assert "supersedes" not in node


def test_kind_mapping():
    lignes = [
        {"id": "a", "ligne_type": "ARTICLE", "ligne_libelle_1": "ARTICLE 6",
         "ligne_libelle_compl_1": "(suite)", "ligne_video_highlighted": "true"},
        {"id": "b", "ligne_type": "SSADT", "ligne_libelle_1": "S/Adt n° 377",
         "ligne_video_highlighted": "true"},
        {"id": "c", "ligne_type": "INSCRITDG", "ligne_libelle_1": "Mme Sophie RICOURT VAGINAY",
         "depute_tribun_id": "840657", "ligne_video_highlighted": "true"},
        {"id": "d", "ligne_type": "NEXTSEANCEL1", "ligne_libelle_1": "PROCHAINE SÉANCE",
         "ligne_video_highlighted": "true"},
    ]
    nodes = trame.TrameWeaver().feed_snapshot(snapshot(*lignes), t_ms=0)

    kinds = {n["text"]: n["kind"] for n in nodes}
    assert kinds["ARTICLE 6 (suite)"] == "article"       # compl appended
    assert kinds["S/Adt n° 377"] == "amendment"
    assert kinds["Mme Sophie RICOURT VAGINAY"] == "speaker"
    assert kinds["PROCHAINE SÉANCE"] == "phase"


def test_canonical_absent_fields_are_null():
    ligne = {"id": "x", "ligne_type": "LIBRE", "ligne_libelle_1": "Fin de vie (suite)",
             "ligne_video_highlighted": "true"}
    (node,) = trame.TrameWeaver().feed_snapshot(snapshot(ligne), t_ms=0)

    assert node["canonical"] == {"acteur": None, "tribun": None,
                                 "amendement_uid": None, "scrutin": None,
                                 "article": None}


def test_still_highlighted_emits_nothing():
    tw = trame.TrameWeaver()
    assert len(tw.feed_snapshot(snapshot(adt()), t_ms=0)) == 1
    assert tw.feed_snapshot(snapshot(adt()), t_ms=5000) == []


def test_exit_emits_nothing_and_reentry_emits_again():
    tw = trame.TrameWeaver()
    tw.feed_snapshot(snapshot(adt()), t_ms=0)
    assert tw.feed_snapshot(snapshot(adt(highlighted=False)), t_ms=5000) == []
    (again,) = tw.feed_snapshot(snapshot(adt()), t_ms=10000)
    assert again["text"] == "Adt n° 1388 de M. BOVET"
    assert "supersedes" not in again  # a fresh entry, not an update


def test_label_enrichment_supersedes():
    """Same line id, label enriched in place («(scrutin public)» appended)."""
    tw = trame.TrameWeaver()
    (first,) = tw.feed_snapshot(snapshot(adt()), t_ms=0)
    (updated,) = tw.feed_snapshot(
        snapshot(adt(libelle="Adt n° 1388 de M. BOVET (scrutin public)")), t_ms=8000)

    assert updated["supersedes"] == first["seq"]
    assert updated["state"] == "consolidated"
    assert updated["text"].endswith("(scrutin public)")


def test_bare_object_shapes_are_parsed():
    """XML→JSON convention: `phase` and `ligne` are bare objects when single."""
    snap = {"racine": {"contenu": {"phase": {"phase_libelle": "P", "ligne": adt()}}}}
    (node,) = trame.TrameWeaver().feed_snapshot(snap, t_ms=0)
    assert node["kind"] == "amendment"


def test_seq_is_shared_with_the_stt_weaver():
    seq = w.Seq()
    stt = w.Weaver(seq=seq)
    tw = trame.TrameWeaver(seq=seq)

    (a,) = stt.feed({"type": "interim", "beg": 1.0, "text": "un"})
    (b,) = tw.feed_snapshot(snapshot(adt()), t_ms=1500)
    (c,) = stt.feed({"type": "utterance", "beg": 1.0, "end": 2.0, "text": "un deux"})

    assert [a["seq"], b["seq"], c["seq"]] == [0, 1, 2]


@pytest.mark.skipif(not os.path.isdir(BUNDLE), reason="real capture bundle not mounted")
def test_real_bundle_replay_finds_the_bovet_amendment():
    """Acceptance: replaying the 114 real snapshots of 26/06 weaves the trame,
    including Adt n° 1388 de M. BOVET with a complete canonical block."""
    tw = trame.TrameWeaver()
    nodes = []
    for i, path in enumerate(sorted(glob.glob(f"{BUNDLE}/raw/derouleur/*.json"))):
        with open(path) as f:
            nodes += tw.feed_snapshot(json.load(f), t_ms=i * 1000)

    kinds = {n["kind"] for n in nodes}
    assert {"article", "amendment"} <= kinds
    bovet = [n for n in nodes
             if n["canonical"]["amendement_uid"] == "AMANR5L17PO838901BTC2915P0D1N001388"]
    assert bovet, "Adt 1388 BOVET never woven"
    assert bovet[0]["canonical"]["acteur"] == "PA793182"
    # the enriched «(scrutin public)» relabel of the same line supersedes
    assert any("supersedes" in n for n in nodes)
