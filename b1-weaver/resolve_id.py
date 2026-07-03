"""Canonical ID resolver (spec 2026-07-01-canonical-id-resolution, issue #9).

Detected name (noisy, STT-side) -> canonical uid (PA<tribun>), matched against the
sitting's actor set (referential/acteurs.json). Pure: no GPU, no network.

Honesty over a wrong ID (TDC03): a title-only phrase, an absent name, or an
ambiguous bare surname resolve to None, never to a guessed uid.
"""
import unicodedata
from difflib import SequenceMatcher

# civility + function/title words stripped before matching (never part of a name)
_STOP = {
    "m", "mme", "mlle", "monsieur", "madame", "mademoiselle",
    "le", "la", "les", "l", "de", "du", "des",
    "president", "presidente", "ministre", "secretaire", "depute", "deputee",
    "rapporteur", "rapporteure", "rapporteure", "orateur", "oratrice",
}


def _norm(s):
    """Lowercase, strip accents (NFKD), keep letters/spaces/hyphens, collapse spaces."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = "".join(c if (c.isalpha() or c in " -") else " " for c in s)
    return " ".join(s.split())


def _name_tokens(s):
    """Normalized tokens with civility/title words removed."""
    return [t for t in _norm(s).split() if t not in _STOP]


def _ratio(a, b):
    return SequenceMatcher(None, a, b).ratio()


def resolve(name, actors, threshold=0.72):
    """Resolve a detected name to {uid, score, nom} or None.

    - single token -> matched as a surname; if >1 actor shares it, None (ambiguous)
    - multiple tokens -> matched against the full "prenom nom"
    Below threshold, or a full-name tie across distinct actors, -> None.
    """
    q_tokens = _name_tokens(name)
    if not q_tokens:
        return None
    q = " ".join(q_tokens)

    if len(q_tokens) == 1:  # bare surname
        scored = sorted(((_ratio(q, _norm(a["nom"])), a) for a in actors),
                        key=lambda x: -x[0])
        best_score, best = scored[0]
        if best_score < threshold:
            return None  # absent
        # ambiguous means TOO CLOSE (spec D3), not merely a second hit over the
        # floor: real case «Bruet» → Gruet .800 / Barbut .727, the best wins
        ties = [a for s, a in scored if s >= best_score - 0.05]
        if len({a["uid"] for a in ties}) > 1:
            return None
        return {"uid": best["uid"], "score": round(best_score, 3), "nom": best["nom"]}

    scored = sorted(
        ((_ratio(q, _norm(a["prenom"] + " " + a["nom"])), a) for a in actors),
        key=lambda x: -x[0],
    )
    best_score, best = scored[0]
    if best_score < threshold:
        return None
    ties = [a for s, a in scored if s >= best_score - 0.02]
    if len({a["uid"] for a in ties}) > 1:
        return None  # too close to call
    return {"uid": best["uid"], "score": round(best_score, 3), "nom": best["nom"]}
