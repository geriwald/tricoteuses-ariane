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
import unicodedata

import resolve_id
import weaver as w

# a sentence must name one of these before digits count as amendment numbers
_TRIGGER = re.compile(r"amendement|scrutin|voi[xe]", re.I)
_NUMBER = re.compile(r"\b(\d{1,4})\b")
_ARTICLE_NUM = re.compile(r"article\s+(\d{1,4})", re.I)
# a chair's numbered floor-call — «Le 310, Madame de Pélichy» / «186, Madame Catala»:
# a number at a call position (sentence start, or after «le») immediately followed by
# «, [civilité]». Lets the amendment be recognised without an amendement/scrutin word.
# Anchored so «à 15h30, Madame …» (the digits sit after «h», not «le»/start) does NOT fire.
_CALL_NUMBER = re.compile(
    r"(?:^|[.!?]\s*|\ble\s+)(?:n[°ºo]\s*)?\d{1,4}\s*,\s*(?:monsieur|madame|m\.|mme)\b", re.I)
_AMDT_UID_NUM = re.compile(r"N(\d{6})$")

# civility + capitalized name(s); bare titles slip through on purpose — the
# resolver is what refuses them (title-only → None, D3). Nobiliary particles
# (de/du/des/d') and «le/la» may sit before/between the capitalized parts, e.g.
# «Madame de Pélichy», «Monsieur de La Porte» — the lowercase «de» used to break it.
_NAME_PART = r"(?:(?:l[ea]|de|du|des)\s+|d['’]\s*)"
_SPEAKER = re.compile(
    r"\b(?:[Mm]onsieur|[Mm]adame|M\.|Mme)\s+"
    r"(?:" + _NAME_PART + r")*[A-ZÀÂÉÈÊËÎÏÔÙÛÇ][\w'’-]*"
    r"(?:\s+(?:" + _NAME_PART + r")*[A-ZÀÂÉÈÊËÎÏÔÙÛÇ][\w'’-]*)*")

_BALLOT_OPEN = re.compile(r"scrutin\s+est\s+ouvert", re.I)
_BALLOT_VOTE = re.compile(r"met(?:s|tre)?\s+aux?\s+voi[xe]", re.I)
_BALLOT_REJECT = re.compile(r"(?:est|sont)\s+rejeté|n[e'’]\s*(?:est|sont)\s+pas\s+adopté", re.I)
_BALLOT_ADOPT = re.compile(r"(?:est|sont)\s+adoptés?", re.I)

# a result proclamation reads out the TALLY, so its digits are vote counts, never
# amendment numbers («Résultat du scrutin, nombre de votes en 30 … majorité 16 pour,
# 10 contre 20») — reading them as amendments weaves phantom lines AND steals the
# current-amendment context from the scrutin the OCR screen is about
_RESULT_PROCLAMATION = re.compile(
    r"résultat\s+du\s+scrutin|nombre\s+de\s+vot(?:es|ants)|tous?\s+exprimé"
    r"|l['’]assemblée\s+(?:a|n['’]a\s+pas)\s+adopté|majorité\s+\d", re.I)

EMPTY_CANONICAL = {"acteur": None, "tribun": None, "amendement_uid": None,
                   "scrutin": None, "article": None, "groupe": None, "dossier": None}

_BALLOT_LABEL = {"open": "Scrutin ouvert", "vote": "Mise aux voix",
                 "adopted": "Adopté", "rejected": "Rejeté"}


def _aslist(x):
    """derouleur.json comes from XML: a single child is a bare object, not a list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def extract_amendment_numbers(text):
    """Amendment numbers heard in an utterance, in order, deduped.

    Digits only count when the utterance carries an amendment/vote trigger word,
    and «article N» numbers are excluded («l'amendement 1242 à l'article 6» → 1242).
    Result-proclamation CLAUSES are dropped sentence by sentence — their digits are
    vote counts, not amendments («… Madame la rapporteure, 292. Résultat du scrutin,
    majorité 16 pour 10 contre 20.» → [292], never the tally). Robustness comes from
    the agenda lookup downstream: numbers not on the agenda resolve to nothing."""
    if not (_TRIGGER.search(text) or _CALL_NUMBER.search(text)):
        return []
    out = []
    for sentence in re.split(r"[.!?]+", text):
        if _RESULT_PROCLAMATION.search(sentence):
            continue  # a tally clause: «majorité 16 pour, 10 contre 20» — counts
        for n in _numbers_excluding_articles(sentence):
            if n not in out:
                out.append(n)
    return out


def _numbers_excluding_articles(text):
    """Numbers in a sentence, in order, deduped, minus «article N» ones. No trigger
    gate — the caller already knows these digits are amendment numbers."""
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


# a call context reaching back from the name — but only NEAR it (≤40 chars): a
# chair's «merci / la parole est à … [Nom]» is short, whereas a deputy's speech
# «Merci Madame la Présidente, … que celui de [Nom]» merely thanks the chair and
# mentions a colleague 80 chars later — that is not a call
_CALL_BEFORE = re.compile(r"(?:la parole est à|merci\b|je vous remercie)[^.!?]{0,40}$", re.I)
_CALL_AFTER = re.compile(r"^\s*[,–—]?\s*(?:du|pour le)\s+groupe", re.I)
_CALL_AFTER_PURPOSE = re.compile(
    r"^\s*[,–—]?\s*pour\s+(?:le|la|l['’])\s+"
    r"(?:pr[ée]senter|d[ée]fendre|soutenir|haut)\b", re.I)
_CALL_AFTER_NUMBER = re.compile(
    r"^\s*[,–—]?\s*(?:le|l['’]amendement)\s+\d{1,4}\b", re.I)
_CALL_BEFORE_SHORT_ITEM = re.compile(
    r"(?:^|[.!?]\s*)(?:merci\s*[.!?]\s*)?"
    r"(?:l['’]identique|(?:le\s+)?\d{1,4})\s*,?\s*$", re.I)
_PENDING_CALL_CONTINUATION = re.compile(
    r"^\s*(?:vous\s+)?(?:vouliez|voulez|souhaitiez|souhaitez)\s+"
    r"reprendre\s+la\s+parole\b", re.I)


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
    sentence_before = re.split(r"[.!?]", before)[-1]
    if _CALL_AFTER.search(after):
        return "strong"
    if not sentence_before.strip() and _CALL_AFTER_PURPOSE.search(after):
        return "strong"
    if (not sentence_before.strip() or _CALL_BEFORE_SHORT_ITEM.search(before)):
        if _CALL_AFTER_NUMBER.search(after):
            return "strong"
    if _CALL_BEFORE.search(before):
        return "strong"
    if _CALL_BEFORE_SHORT_ITEM.search(before):
        sentence_after = re.split(r"[.!?]", after, maxsplit=1)[0]
        if not sentence_after.strip():
            return "strong"
    # an amendment context IMMEDIATELY before the name («L'amendement 449, madame
    # Bruet, défendu») — but «amendement» as a common noun deep in a speech («il
    # s'agit d'un amendement plus restreint … que celui de [Nom]») is not a call
    if re.search(r"amendements?\b[^.!?]{0,40}$", before, re.I):
        return "strong"
    # sentence-level: a name that IS its own sentence («…il faut que je
    # tienne. Monsieur David Topiac.») — a call shape, but ambiguous
    if not sentence_before.strip():
        sentence_after = re.split(r"[.!?]", after, maxsplit=1)[0]
        if not sentence_after.strip():
            return "weak"  # bare-name sentence: needs voice corroboration
    return False


def is_pending_speaker_call_tail(text, name):
    """Name left dangling at an utterance boundary.

    LocalAgreement can split a chair's call as «Madame X,» / «vous vouliez
    reprendre la parole ?». The first chunk alone is not enough to call the
    floor; the next chunk must corroborate it.
    """
    idx = text.find(name)
    if idx < 0:
        return False
    after = text[idx + len(name):]
    return bool(re.fullmatch(r"\s*[,–—]\s*", after))


# mic role announced by a chair's title-call. The PERSON stays unresolved (no
# referential carries the sitting role — resolution-referentiels-canutes.md);
# the FUNCTION is the honest thing the STT gives. Calibrated on the 02/07 STT
# («Madame la rapporteure, votre avis ?», «Monsieur le ministre.»).
_ROLE_PATTERNS = [
    ("rapporteur", "la rapporteure",
     re.compile(r"(?:madame|monsieur)\s+l[ae]\s+rapporteur[e]?s?\b", re.I)),
    ("ministre", "le ministre",
     re.compile(r"(?:madame|monsieur)\s+l[ae]\s+ministre\b"
                r"|garde\s+des\s+sceaux\b"
                r"|secr[ée]taire\s+d['’]?[ée]tat\b", re.I)),
    ("president", "la présidence",
     re.compile(r"(?:madame|monsieur)\s+l[ae]\s+président[e]?\b", re.I)),
]


def extract_role(text):
    """The mic role announced by a chair's title-call, deduced from text.

    Returns (role, label) for the first title that reads as a CALL (a handoff),
    else None — a mere mention («je pense que la rapporteur a raison») moves
    nothing. The président is chronically THANKED («merci Madame la Présidente»);
    that politeness is not a handoff, so it is excluded."""
    for role, label, pat in _ROLE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if role == "president" and re.search(r"(?:merci|remercie)[^.]*$",
                                             text[:m.start()], re.I):
            continue
        if is_speaker_call(text, m.group(0)):
            return role, label
    return None


# avis (commission/gouvernement) deduced from the debate wording
_AVIS_HAS = re.compile(r"\bavis\b|\bsagesse\b|titre\s+personnel", re.I)
_AVIS_DOUBLE = re.compile(r"double\s+avis\s+(favorable|défavorable)", re.I)
_AVIS_SENS = re.compile(r"\b(défavorable|defavorable|favorable|sagesse)\b", re.I)
_ORGANE_NEAR = re.compile(r"commission|gouvernement|gouverneur", re.I)
_SENS_NORM = {"favorable": "favorable", "défavorable": "defavorable",
              "defavorable": "defavorable", "sagesse": "sagesse"}
_ROLE_ORGANE = {"rapporteur": "commission", "ministre": "gouvernement"}
_AVIS_DISPLAY = {"favorable": "favorable", "defavorable": "défavorable",
                 "sagesse": "sagesse"}


def _organe_near(text, start, end):
    """The organe cue nearest a sens token: «de la commission» / «du
    gouvernement» (STT «gouverneur») after it, else just before it."""
    m = _ORGANE_NEAR.search(text, end, end + 40)
    if not m:
        for mm in _ORGANE_NEAR.finditer(text, max(0, start - 40), start):
            m = mm  # keep the last (closest) cue before the sens
    if not m:
        return None
    return "commission" if m.group(0).lower() == "commission" else "gouvernement"


def extract_avis(text, speaker_role=None):
    """Avis (commission/gouvernement) deduced from an utterance.

    «double avis X» = the chair reporting BOTH benches → two nodes. Otherwise
    each favorable/défavorable/sagesse is tied to the nearest explicit organe
    cue («de la commission», «du gouvernement»). With no explicit organe, the
    sens counts only if the utterance frames it as an avis («avis», «sagesse»,
    «titre personnel»), and the current mic role infers the bench
    (rapporteur→commission, ministre→gouvernement) — no cue, no marker/role →
    nothing (honesty over coverage)."""
    m = _AVIS_DOUBLE.search(text)
    if m:
        sens = _SENS_NORM[m.group(1).lower()]
        return [{"organe": "commission", "sens": sens},
                {"organe": "gouvernement", "sens": sens}]
    has_marker = bool(_AVIS_HAS.search(text))
    out, seen = [], set()
    for sm in _AVIS_SENS.finditer(text):
        organe = _organe_near(text, sm.start(), sm.end())
        if organe is None:
            organe = _ROLE_ORGANE.get(speaker_role) if has_marker else None
        if organe is None or organe in seen:
            continue
        seen.add(organe)
        out.append({"organe": organe, "sens": _SENS_NORM[sm.group(1).lower()]})
    return out


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


# scrutin public: the derouleur libellé already carries «(scrutin public)» on a
# pre-marked amendment (parsed here into a flag, the badge's honest source); the
# chair ALSO announces it in speech, often crediting the requesting group(s)
# («demande de scrutin public par le groupe LFI-NFP», «demandé respectivement
# par les groupes La France insoumise et LIOT»). Those groups resolve to the
# organes referential like every other heard entity.
_SCRUTIN_PUBLIC_LIBELLE = re.compile(r"\(\s*scrutin\s+public\s*\)", re.I)
_SCRUTIN_PUBLIC = re.compile(r"scrutin\s+public", re.I)
# a demandeur is CREDITED, not merely named: «par le(s) groupe(s) X» / «à la demande
# du groupe X». «du/pour le groupe X» (the membership form of a floor call) is
# deliberately NOT a request, so «la parole est à Mme X du groupe Y» is never one.
_DEMANDEUR_TAIL = re.compile(
    r"(?:par\s+(?:les?\s+|des\s+)?groupes?"
    r"|à\s+la\s+demande\s+(?:du|des|de\s+l[ae'’])\s*groupes?)\s+([^.!?]+)", re.I)
_RESPECTIVEMENT = re.compile(r"respectivement", re.I)


def _norm_groupe(s):
    """Group label -> comparable key: accents/spaces/punctuation dropped, lower
    («La France insoumise - NFP» -> «lafranceinsoumisenfp», «LIOT» -> «liot»)."""
    nfkd = unicodedata.normalize("NFKD", s or "")
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_.lower())


def resolve_groupe(heard, organes):
    """Heard group name -> its organe (uid/libellé/abrégé) or None (PURE).

    Accent/space/punct-insensitive, matching on the abrégé (LFI-NFP, LIOT, RN)
    or the full libellé as a prefix: «Liottes» (STT) -> LIOT, «La France
    Insoumise» -> LFI-NFP, «LFI, NFP» -> LFI-NFP. A comma inside a heard name is
    part of it («LFI, NFP»), so we also try its first segment as a fallback.
    None when nothing plausibly matches — honesty over coverage."""
    variants = [heard]
    head = heard.split(",", 1)[0]
    if head != heard:
        variants.append(head)
    best = None
    for raw in variants:
        h = _norm_groupe(raw)
        if len(h) < 2:
            continue
        for o in organes:
            if o.get("code_type") != "GP":
                continue
            ab = _norm_groupe(o.get("libelle_abrege"))
            lib = _norm_groupe(o.get("libelle"))
            score = None
            if ab and h == ab:
                score = 3
            elif (ab and min(len(h), len(ab)) >= 3
                  and 2 * min(len(h), len(ab)) >= max(len(h), len(ab))
                  and (h.startswith(ab) or ab.startswith(h))):
                # the shorter must cover ≥ half the longer: «liottes»/«liot» ok,
                # «soclecommun»/«soc» rejected (a phrase merely starting with an abrégé)
                score = 2
            elif lib and len(h) >= 4 and (lib.startswith(h) or h.startswith(lib)):
                score = 1
            if score is not None and (best is None or score > best[0]):
                best = (score, o)
    return best[1] if best else None


def extract_demandeurs(text):
    """Group names a chair CREDITS for requesting a public ballot, as heard.

    Fires only on a crediting clause «par le(s) groupe(s) X» / «à la demande du
    groupe X» — never on «du/pour le groupe X», the membership form of a floor call
    («la parole est à Mme X du groupe Y»). Returns the raw tokens in order («X et Y»
    -> [X, Y]); an internal comma stays inside a name («LFI, NFP»). Resolution and
    the scrutin-public context gate are the caller's job."""
    m = _DEMANDEUR_TAIL.search(text)
    if not m:
        return []
    parts = re.split(r"\s+et\s+|\s*;\s*", m.group(1), flags=re.I)
    return [p.strip(" ,.–—") for p in parts if p.strip(" ,.–—")]


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

    def __init__(self, agenda, actors, organes=None, seq=None, amendments=None):
        self.agenda = agenda  # replaceable by the live agenda poller
        self.set_referentials(actors, organes, amendments)
        self._seq = seq or w.Seq()
        self._woven_uids = set()
        self._current = None  # canonical of the last amendment heard
        self._speaker_uid = None
        self._speaker_role = None  # deduced mic role, for avis organe inference
        self._prev_tail = None  # previous utterance, for cross-utterance sentences
        self._pending_speaker = None  # name split before a handoff continuation
        self._scrutin_pending = None  # amdts announced «scrutin public», awaiting demandeur
        self._voting = None  # amdt whose scrutin is OPEN — the OCR result attaches to IT,
                             # not to _current (which may have moved to the next amendment)

    def set_referentials(self, actors, organes=None, amendments=None):
        """Swap the lookup dictionaries in place — sittings follow one another
        on a live flow, so referentials are polled, never a restart reason."""
        self.actors = actors
        # groupe uid → libelle, from the sitting's organes.json referential
        self._groupe_label = {o["uid"]: o["libelle"] for o in (organes or [])}
        # the whole organes list too, to resolve a heard demandeur group by name
        self._organes = list(organes or [])
        # amendment uid → dossier uid (DLR…), from the amendements.json referential
        # — the dossier is not derivable from the uid, only the referential carries it
        self._dossier_by_uid = {a["uid"]: a.get("dossier")
                                for a in (amendments or []) if a.get("dossier")}

    def _node(self, t, kind, text, canonical, source="stt"):
        return {"t": t, "seq": self._seq.next(), "kind": kind,
                "state": "consolidated", "text": text,
                "canonical": canonical, "source": source}

    def feed(self, node):
        """Consume one thread node; return the trame nodes it lets us deduce."""
        if node.get("kind") != "utterance" or node.get("state") != "consolidated":
            return []
        text, t = node["text"], node["t"]
        out = []

        pending = self._pending_speaker
        self._pending_speaker = None
        if pending and _PENDING_CALL_CONTINUATION.search(text):
            self._speaker_uid = pending["uid"]
            self._speaker_role = None
            node = self._node(pending["t"], "speaker", pending["label"],
                              pending["canonical"])
            node["call"] = "strong"
            node["heard"] = pending["heard"]
            if pending["groupe"] in self._groupe_label:
                node["groupe_label"] = self._groupe_label[pending["groupe"]]
            out.append(node)

        amdt_targets = []  # canonicals heard this utterance, in order (scrutin-public binding)
        for num in extract_amendment_numbers(text):
            e = self.agenda.lookup(num)
            if e is None:
                continue  # not on the agenda: honesty over coverage
            canonical = self._amendment_canonical(e)
            # when several amendments are announced together («176 et 310»), the
            # debate opens on the FIRST — it is discussed before the next; a later
            # utterance naming one of them alone re-anchors the context to it
            if not amdt_targets:
                self._current = canonical
            amdt_targets.append(canonical)
            if e["uid"] in self._woven_uids:
                continue
            self._woven_uids.add(e["uid"])
            node = self._node(t, "amendment", e["libelle"], canonical)
            # scrutin public: the derouleur pre-marks it in the libellé (authoritative);
            # a group-named request also marks it, via the scrutin_public node below
            if _SCRUTIN_PUBLIC_LIBELLE.search(e["libelle"] or ""):
                node["scrutin_public"] = True
            out.append(node)

        out += self._scrutin_public(text, t, amdt_targets)

        for name in extract_speaker_names(text):
            r = resolve_id.resolve(name, self.actors)
            if r is None or r["uid"] == self._speaker_uid:
                continue  # title-only/unknown/ambiguous, or the current speaker
            call = is_speaker_call(text, name, prev_tail=self._prev_tail)
            actor = next((a for a in self.actors if a["uid"] == r["uid"]), None)
            label = (f"{actor['civ']} {actor['prenom']} {actor['nom']}"
                     if actor else r["nom"])
            groupe = (actor or {}).get("groupe_uid")
            canonical = dict(EMPTY_CANONICAL,
                             acteur=r["uid"], tribun=r["uid"][2:],
                             groupe=groupe)
            if call:
                self._speaker_uid = r["uid"]  # a mention never moves the floor
                self._speaker_role = None     # a named deputy: role unknown, not claimed
            elif is_pending_speaker_call_tail(text, name):
                self._pending_speaker = {"t": t, "uid": r["uid"],
                                         "label": label, "canonical": canonical,
                                         "heard": name, "groupe": groupe}
            node = self._node(t, "speaker", label, canonical)
            node["call"] = call
            node["heard"] = name  # the misheard form, for inline text repair
            if groupe in self._groupe_label:
                node["groupe_label"] = self._groupe_label[groupe]
            out.append(node)

        role = extract_role(text)
        if role:
            r_name, label = role
            self._speaker_role = r_name  # holds even when deduped (avis inference)
            key = f"@role:{r_name}"
            if key != self._speaker_uid:
                self._speaker_uid = key   # the mic changed hands
                node = self._node(t, "speaker", label, dict(EMPTY_CANONICAL))
                node["call"] = "strong"
                node["role"] = r_name
                out.append(node)

        for a in extract_avis(text, self._speaker_role):
            canonical = dict(self._current) if self._current else dict(EMPTY_CANONICAL)
            node = self._node(t, "avis",
                              f"Avis {a['organe']} : {_AVIS_DISPLAY[a['sens']]}", canonical)
            node["organe"], node["sens"] = a["organe"], a["sens"]
            out.append(node)

        action = extract_ballot(text)
        if action:
            canonical = dict(self._current) if self._current else dict(EMPTY_CANONICAL)
            if action in ("open", "vote"):
                self._voting = canonical  # this amendment is now under the open scrutin
            out.append(self._node(t, "ballot", _BALLOT_LABEL[action], canonical))

        self._prev_tail = text
        return out

    def _amendment_canonical(self, e):
        """Canonical from an agenda entry (acteur/tribun/uid/article/dossier)."""
        return dict(EMPTY_CANONICAL,
                    acteur=f"PA{e['tribun']}" if e["tribun"] else None,
                    tribun=e["tribun"], amendement_uid=e["uid"],
                    article=e["article"], dossier=self._dossier_by_uid.get(e["uid"]))

    def _scrutin_public(self, text, t, amdt_targets):
        """Nodes crediting the group(s) that REQUESTED a public ballot.

        A demandeur clause («par le groupe X») is credited only in a real
        scrutin-public context: the utterance itself says «scrutin public», or a
        prior announcement is awaiting its group. The announcement and its
        demandeur can split across utterances («…176 et 310, je suis saisie de
        scrutin public» then «demandé respectivement par les groupes …»): the
        first parks its amendments in _scrutin_pending for the IMMEDIATELY next
        utterance (it expires after one, so a much later demande can't bind to a
        stale announcement). «respectivement» with matching counts maps group i to
        amendment i; otherwise every named group is credited on each target."""
        prev_pending = self._scrutin_pending
        self._scrutin_pending = None  # a parked announcement lives one utterance only

        heard = extract_demandeurs(text)
        scrutin_here = bool(_SCRUTIN_PUBLIC.search(text))
        if not heard:
            if scrutin_here and amdt_targets:   # announced, group not yet named → park
                self._scrutin_pending = amdt_targets
            return []
        if not (scrutin_here or prev_pending):
            return []   # «à la demande du groupe X, la séance est suspendue» — not a ballot

        # credit the amendment ANNOUNCED before the «groupe …» clause, not those that
        # follow in the same STT-merged utterance («…sur les 76 … par le groupe X.
        # Ensuite, sur les 77 …» → 76). No trigger needed: we already know it's a demande.
        m = _DEMANDEUR_TAIL.search(text)
        before = [self.agenda.lookup(n) for n in _numbers_excluding_articles(text[:m.start()])]
        before = [self._amendment_canonical(e) for e in before if e]
        targets = before or amdt_targets or prev_pending or (
            [self._current] if self._current else [])
        if not targets:
            return []

        groups = [self._resolve_demandeur(h) for h in heard]
        if _RESPECTIVEMENT.search(text) and len(groups) == len(targets) and len(targets) > 1:
            pairs = [(targets[i], [groups[i]]) for i in range(len(targets))]
        else:
            pairs = [(tgt, groups) for tgt in targets]

        out = []
        for tgt, grps in pairs:
            node = self._node(t, "scrutin_public",
                              "Scrutin public — " + ", ".join(g["label"] for g in grps),
                              dict(tgt))
            node["demandeurs"] = grps
            out.append(node)
        return out

    def _resolve_demandeur(self, heard):
        """Heard group -> {label, groupe, heard}; label/uid from organes when it
        resolves, else the heard text verbatim (never invented)."""
        o = resolve_groupe(heard, self._organes)
        if o:
            return {"label": o["libelle"], "groupe": o["uid"], "heard": heard}
        return {"label": heard, "groupe": None, "heard": heard}

    def feed_scrutin_result(self, event):
        """Tisser un nœud ballot CHIFFRÉ depuis l'écran-résultat OCRisé (source=ocr).

        La régie incruste dans la vidéo un écran portant le chiffré GLOBAL (votants/
        exprimés/majorité/POUR/CONTRE) mais NI le numéro de scrutin NI le nominatif.
        L'OCR de cet écran (spike 2026-07-03-scrutin-ocr) est une lecture MACHINE de la
        vidéo publique — pas un signal saisi en régie, l'invariant tient. Le chiffré
        s'attache à l'amendement courant, comme les ballots déduits du STT ; le sort se
        déduit du seuil de majorité absolue affiché. `canonical.scrutin` reste None : le
        numéro et le nominatif se résolvent APRÈS séance (resolve_scrutin, contre
        l'open-data assemblee.scrutins).

        `event` = l'event scrutin_result du scanner OCR (t_ms + compteurs + confidence).
        """
        pour, majorite = event.get("pour"), event.get("majorite")
        if pour is not None and majorite is not None:
            text = _BALLOT_LABEL["adopted" if pour >= majorite else "rejected"]
        else:
            text = "Résultat du scrutin"
        # the figures belong to the amendment PUT TO THE VOTE (scrutin ouvert), which
        # may differ from _current once the chair has called the next amendment
        base = self._voting or self._current
        canonical = dict(base) if base else dict(EMPTY_CANONICAL)
        node = self._node(event["t_ms"], "ballot", text, canonical, source="ocr")
        node["result"] = {k: event.get(k) for k in
                          ("votants", "exprimes", "majorite", "pour", "contre",
                           "abstentions")}
        node["confidence"] = event.get("confidence")
        return [node]
