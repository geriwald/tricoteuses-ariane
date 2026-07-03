"""EVAL-ONLY — the régie's highlight as a measuring stick, NEVER a thread source.

This reads what the régie hand-keys into the dérouleur (ligne_video_highlighted).
Ariane REPLACES the régie: its thread is deduced from speech, so this signal must
never feed the thread (its weaving spec was rejected 2026-07-02 — see the removal
commit). Two further caveats from the spike (README.md:70 of the 2026-06-23 spike):
the highlight is a coarse 24-31-line block, not a current-line cursor, and the
official doc says the dérouleur carries no current-line marker at all.

Kept only to *measure* Ariane's speech-deduced trame against what the régie
displayed (the demo's delta argument). Pure and network-free.
"""
import weaver as w

# ligne_type → thread node kind (spec archi §Thread event format)
KIND_BY_TYPE = {
    "ARTICLE": "article",
    "ADT": "amendment",
    "SSADT": "amendment",
    "INSCRIT": "speaker",
    "INSCRITDG": "speaker",
    "INSCRITQAG": "speaker",
    "INTERVCOMMISS": "speaker",
    "INTERVGVT": "speaker",
}


def _aslist(x):
    """derouleur.json comes from XML: a single child is a bare object, not a list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def highlighted_lines(snapshot):
    """The régie's current point: every highlighted line, in document order."""
    contenu = snapshot["racine"]["contenu"]
    return [ligne
            for phase in _aslist(contenu.get("phase"))
            for ligne in _aslist(phase.get("ligne"))
            if ligne.get("ligne_video_highlighted") == "true"]


def _text(ligne):
    parts = [ligne.get("ligne_libelle_1", ""), ligne.get("ligne_libelle_compl_1", "")]
    return " ".join(p for p in parts if p)


def _canonical(ligne):
    tribun = ligne.get("depute_tribun_id") or None
    return {
        "acteur": f"PA{tribun}" if tribun else None,
        "tribun": tribun,
        "amendement_uid": ligne.get("ligne_amendement_uid") or None,
        "scrutin": None,
        "article": None,
    }


class TrameWeaver:
    def __init__(self, seq=None):
        self._seq = seq or w.Seq()
        self._active = {}  # ligne id → {"seq": int, "text": str} while highlighted

    def feed_snapshot(self, snapshot, t_ms):
        """Consume one dérouleur snapshot, return the nodes its transitions produce."""
        nodes = []
        seen = set()
        for ligne in highlighted_lines(snapshot):
            lid = ligne.get("id")
            seen.add(lid)
            text = _text(ligne)
            prev = self._active.get(lid)
            if prev is not None and prev["text"] == text:
                continue  # still highlighted, unchanged — nothing new to weave
            node = {
                "t": t_ms,
                "seq": self._seq.next(),
                "kind": KIND_BY_TYPE.get(ligne.get("ligne_type"), "phase"),
                "state": "consolidated",
                "text": text,
                "canonical": _canonical(ligne),
                "source": "derouleur",
            }
            if prev is not None:
                node["supersedes"] = prev["seq"]  # in-place label enrichment
            self._active[lid] = {"seq": node["seq"], "text": text}
            nodes.append(node)
        # lines that left the highlight: forget them so a re-entry weaves anew
        for lid in list(self._active):
            if lid not in seen:
                del self._active[lid]
        return nodes
