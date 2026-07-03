"""B1 ariane-weaver — speech-deduced trame (spec 2026-07-02-b1-speech-deduced-trame).

The thread's spine — amendments under discussion, speakers, ballots — is DEDUCED
from what the STT heard, then translated into canonical ids via public lookup
referentials only: the derouleur agenda LIST (highlight ignored) and acteurs.json.
Never the régie's hand-keyed signals — Ariane replaces the régie (spec invariant).

Pure and network-free: fetching referentials and live wiring live in weaver_live.
Patterns are calibrated on the real offline transcript of the 26/06 sitting,
including its STT noise («je mets au voie», «madame Bruet» for GRUET).
"""
import re

import resolve_id
import weaver as w

# a sentence must name one of these before digits count as amendment numbers
_TRIGGER = re.compile(r"amendement|scrutin|voi[xe]", re.I)
_NUMBER = re.compile(r"\b(\d{1,4})\b")
_ARTICLE_NUM = re.compile(r"article\s+(\d{1,4})", re.I)
_AMDT_UID_NUM = re.compile(r"N(\d{6})$")

# civility + capitalized name(s); bare titles slip through on purpose — the
# resolver is what refuses them (title-only → None, D3)
_SPEAKER = re.compile(
    r"\b(?:[Mm]onsieur|[Mm]adame|M\.|Mme)\s+"
    r"(?:l[ea]\s+)?[A-ZÀÂÉÈÊËÎÏÔÙÛÇ][\w'’-]*(?:\s+[A-ZÀÂÉÈÊËÎÏÔÙÛÇ][\w'’-]*)*")

_BALLOT_OPEN = re.compile(r"scrutin\s+est\s+ouvert", re.I)
_BALLOT_VOTE = re.compile(r"met(?:s|tre)?\s+aux?\s+voi[xe]", re.I)
_BALLOT_REJECT = re.compile(r"(?:est|sont)\s+rejeté|n[e'’]\s*(?:est|sont)\s+pas\s+adopté", re.I)
_BALLOT_ADOPT = re.compile(r"(?:est|sont)\s+adoptés?", re.I)

EMPTY_CANONICAL = {"acteur": None, "tribun": None, "amendement_uid": None,
                   "scrutin": None, "article": None, "groupe": None}

_BALLOT_LABEL = {"open": "Scrutin ouvert", "vote": "Mise aux voix",
                 "adopted": "Adopté", "rejected": "Rejeté"}


def _aslist(x):
    """derouleur.json comes from XML: a single child is a bare object, not a list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def extract_amendment_numbers(text):
    """Amendment numbers heard in a sentence, in order, deduped.

    Digits only count when the sentence carries an amendment/vote trigger word,
    and «article N» numbers are excluded («l'amendement 1242 à l'article 6» → 1242).
    Robustness comes from the agenda lookup downstream: numbers not on the agenda
    resolve to nothing."""
    if not _TRIGGER.search(text):
        return []
    exclude = set(_ARTICLE_NUM.findall(text))
    out = []
    for m in _NUMBER.finditer(text):
        if m.group(1) in exclude:
            continue
        n = int(m.group(1))
        if n not in out:
            out.append(n)
    return out


def extract_speaker_names(text):
    """«civility + Name» calls, as heard (the resolver rejects bare titles)."""
    return _SPEAKER.findall(text)


# a call context reaching back from the name to the sentence start
_CALL_BEFORE = re.compile(r"(?:la parole est à|merci\b|je vous remercie)[^.!?]*$", re.I)
_CALL_AFTER = re.compile(r"^\s*[,–—]?\s*(?:du|pour le)\s+groupe", re.I)


def is_speaker_call(text, name, prev_tail=None):
    """True if `name` is a chair's CALL (a turn opens); False for a mere
    MENTION (a name quoted inside a speech — real case: the minister citing
    «Mme Arouin-Léauté, sauf erreur» — must not break the turn).

    Call signals: the utterance starts with the name; merci / je vous
    remercie / la parole est à reaching the name; «du|pour le groupe» right
    after it; an amendment context before it («L'amendement 449, madame
    Bruet, défendu»). Default is mention — the least destructive reading.

    prev_tail: the previous consolidated utterance. When it ends mid-sentence
    (LocalAgreement split «…Sur la réponse pour / Mme Isabelle Santiago.»),
    the name continues THAT sentence — it is judged with that context.

    Returns "strong" | "weak" | False. A bare-name sentence is only a WEAK
    call: a minister answering a series of questions names their authors the
    same way («Qui c'est que j'ai oublié ? Mme Josiane Corneloup.») — the
    reliable discriminant is the VOICE, so weak calls need a diarization
    boundary to corroborate (done by the consumer)."""
    idx = text.find(name)
    if idx < 0:
        return False
    before, after = text[:idx], text[idx + len(name):]
    if not before.strip() and prev_tail and not re.search(r"[.!?…]\s*$", prev_tail.strip()):
        before = prev_tail  # the name continues the previous, unfinished sentence
    if _CALL_AFTER.search(after):
        return "strong"
    if _CALL_BEFORE.search(before):
        return "strong"
    if re.search(r"amendements?\b", before, re.I):
        return "strong"
    # sentence-level: a name that IS its own sentence («…il faut que je
    # tienne. Monsieur David Topiac.») — a call shape, but ambiguous
    sentence_before = re.split(r"[.!?]", before)[-1]
    if not sentence_before.strip():
        sentence_after = re.split(r"[.!?]", after, maxsplit=1)[0]
        if not sentence_after.strip():
            return "weak"  # bare-name sentence: needs voice corroboration
    return False


def extract_ballot(text):
    """Ballot event in a sentence: open | vote | adopted | rejected | None.
    Rejection is tested before adoption («n'est pas adopté» contains «est adopté»)."""
    if _BALLOT_OPEN.search(text):
        return "open"
    if _BALLOT_REJECT.search(text):
        return "rejected"
    if _BALLOT_ADOPT.search(text):
        return "adopted"
    if _BALLOT_VOTE.search(text):
        return "vote"
    return None


class AgendaIndex:
    """number → amendment entry, ACCUMULATED from derouleur agenda LIST snapshots.

    Reads every ADT/SSADT line of the ordre du jour — a public dictionary — and
    deliberately ignores `ligne_video_highlighted` (the régie's cursor).
    Accumulates because the derouleur PURGES already-discussed lines during the
    sitting (verified on the 26/06 capture: 1388 in the first snapshot, gone
    later); an honest live listener remembers the agenda it has seen."""

    def __init__(self):
        self._by_num = {}

    @classmethod
    def from_derouleur(cls, snapshot):
        idx = cls()
        idx.update(snapshot)
        return idx

    def update(self, snapshot):
        """Fold one derouleur snapshot in: new lines add, relabels refresh,
        purged lines are kept (the whole point of accumulating)."""
        contenu = snapshot["racine"]["contenu"]
        for phase in _aslist(contenu.get("phase")):
            for ligne in _aslist(phase.get("ligne")):
                if ligne.get("ligne_type") not in ("ADT", "SSADT"):
                    continue
                m = _AMDT_UID_NUM.search(ligne.get("ligne_amendement_uid") or "")
                if not m:
                    continue
                self._by_num[int(m.group(1))] = {
                    "uid": ligne["ligne_amendement_uid"],
                    "tribun": ligne.get("depute_tribun_id"),
                    "libelle": ligne.get("ligne_libelle_1", ""),
                    "article": ligne.get("ligne_amendement_derouleur_division_ancre"),
                }

    def lookup(self, num):
        return self._by_num.get(num)


class Deducer:
    """Stateful: consolidated utterances in, deduced trame nodes out.

    Context = the last amendment heard (ballots attach to it, the implicit
    subject of «Il est rejeté»). An amendment is woven once (dedup by uid);
    ballots are events and always emitted; a speaker is re-emitted only when
    the speaker changes."""

    def __init__(self, agenda, actors, organes=None, seq=None):
        self.agenda = agenda  # replaceable by the live agenda poller
        self.set_referentials(actors, organes)
        self._seq = seq or w.Seq()
        self._woven_uids = set()
        self._current = None  # canonical of the last amendment heard
        self._speaker_uid = None
        self._prev_tail = None  # previous utterance, for cross-utterance sentences

    def set_referentials(self, actors, organes=None):
        """Swap the lookup dictionaries in place — sittings follow one another
        on a live flow, so referentials are polled, never a restart reason."""
        self.actors = actors
        # groupe uid → libelle, from the sitting's organes.json referential
        self._groupe_label = {o["uid"]: o["libelle"] for o in (organes or [])}

    def _node(self, t, kind, text, canonical):
        return {"t": t, "seq": self._seq.next(), "kind": kind,
                "state": "consolidated", "text": text,
                "canonical": canonical, "source": "stt"}

    def feed(self, node):
        """Consume one thread node; return the trame nodes it lets us deduce."""
        if node.get("kind") != "utterance" or node.get("state") != "consolidated":
            return []
        text, t = node["text"], node["t"]
        out = []

        for num in extract_amendment_numbers(text):
            e = self.agenda.lookup(num)
            if e is None:
                continue  # not on the agenda: honesty over coverage
            canonical = dict(EMPTY_CANONICAL,
                             acteur=f"PA{e['tribun']}" if e["tribun"] else None,
                             tribun=e["tribun"],
                             amendement_uid=e["uid"],
                             article=e["article"])
            self._current = canonical  # even if already woven: context moves
            if e["uid"] in self._woven_uids:
                continue
            self._woven_uids.add(e["uid"])
            out.append(self._node(t, "amendment", e["libelle"], canonical))

        for name in extract_speaker_names(text):
            r = resolve_id.resolve(name, self.actors)
            if r is None or r["uid"] == self._speaker_uid:
                continue  # title-only/unknown/ambiguous, or the current speaker
            call = is_speaker_call(text, name, prev_tail=self._prev_tail)
            if call:
                self._speaker_uid = r["uid"]  # a mention never moves the floor
            actor = next((a for a in self.actors if a["uid"] == r["uid"]), None)
            label = (f"{actor['civ']} {actor['prenom']} {actor['nom']}"
                     if actor else r["nom"])
            groupe = (actor or {}).get("groupe_uid")
            node = self._node(t, "speaker", label,
                              dict(EMPTY_CANONICAL,
                                   acteur=r["uid"], tribun=r["uid"][2:],
                                   groupe=groupe))
            node["call"] = call
            node["heard"] = name  # the misheard form, for inline text repair
            if groupe in self._groupe_label:
                node["groupe_label"] = self._groupe_label[groupe]
            out.append(node)

        action = extract_ballot(text)
        if action:
            canonical = dict(self._current) if self._current else dict(EMPTY_CANONICAL)
            out.append(self._node(t, "ballot", _BALLOT_LABEL[action], canonical))

        self._prev_tail = text
        return out
