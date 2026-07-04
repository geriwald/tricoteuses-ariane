"""Tests for B1 speech-deduced trame (spec 2026-07-02-b1-speech-deduced-trame).

Fixtures are REAL sentences from stt-offline-large-v3.ndjson (sitting of 26/06),
STT noise included («je mets au voie», «madame Bruet» for GRUET). The deducer
turns consolidated utterances into amendment/speaker/ballot nodes, resolved
against public referentials only (derouleur agenda list, acteurs.json) — never
the régie's hand-keyed signals.
"""
import glob
import json
import os

import pytest

import deduce
import weaver as w

BUNDLE = "/mnt/data/ariane-capture/2026-06-26-evening"


# ---- extraction (pure text → raw events) -------------------------------------

def test_extract_amendment_numbers_real_sentences():
    assert deduce.extract_amendment_numbers(
        "Alors, amendement 1240 n'est pas défendu.") == [1240]
    assert deduce.extract_amendment_numbers(
        "je vous indique que sur les amendements 1242 et 1388, il y a des scrutins") == [1242, 1388]
    # bare number, vote context («au voie» is real STT noise for «aux voix»)
    assert deduce.extract_amendment_numbers(
        "Donc je mets au voie le 1388 qui fait l'objet d'un scrutin public.") == [1388]


def test_extract_amendment_numbers_ignores_articles_and_plain_text():
    # «à l'article 6» must not yield 6
    assert deduce.extract_amendment_numbers(
        "l'examen des articles s'arrêtant à l'amendement numéro 1242 à l'article 6.") == [1242]
    # no trigger word → no numbers, even if digits appear
    assert deduce.extract_amendment_numbers("on verra ça à l'article 10.") == []
    assert deduce.extract_amendment_numbers("Il est rejeté.") == []


def test_extract_speaker_names_real_sentences():
    assert deduce.extract_speaker_names("Monsieur Bazin.") == ["Monsieur Bazin"]
    assert deduce.extract_speaker_names(
        "L'amendement 449, madame Bruet, défendu pour la commission.") == ["madame Bruet"]
    # titles are extracted too — the resolver is what rejects them (D3)
    assert "Madame la Présidente" in deduce.extract_speaker_names(
        "Oui, merci Madame la Présidente.")


def test_extract_speaker_names_handles_nobiliary_particle():
    """Lowercase «de/du/d'» particles must not break capture (real: «Madame de
    Pélichy» yielded nothing before)."""
    assert deduce.extract_speaker_names("Le 310, Madame de Pellichy.") == ["Madame de Pellichy"]
    assert deduce.extract_speaker_names("La parole est à Monsieur de Courson.") == ["Monsieur de Courson"]
    assert deduce.extract_speaker_names("Madame de La Porte") == ["Madame de La Porte"]
    # unchanged: plain names and the thanked title still capture as before
    assert deduce.extract_speaker_names("Monsieur Bazin.") == ["Monsieur Bazin"]
    assert "Madame la Présidente" in deduce.extract_speaker_names("Merci Madame la Présidente.")


def test_extract_amendment_numbers_from_numbered_floor_call():
    """A chair's «Le 310, Madame X» / «186, Madame Y» names the amendment without an
    amendement/scrutin word — recognised via the numbered-call pattern, but «15h30»
    (digits after «h», not «le»/start) must NOT fire."""
    assert deduce.extract_amendment_numbers("Le 310, Madame de Pellichy.") == [310]
    assert deduce.extract_amendment_numbers("Le n° 310, Madame de Pélichy.") == [310]
    assert deduce.extract_amendment_numbers("Merci. 186, Madame Catala.") == [186]
    assert deduce.extract_amendment_numbers("à 15h30, Madame la Présidente") == []
    assert deduce.extract_amendment_numbers("on examine le budget 2016, Madame") == []


def test_extract_ballot_real_sentences():
    assert deduce.extract_ballot("Le scrutin est ouvert.") == "open"
    assert deduce.extract_ballot(
        "Donc je mets au voie le 1388 qui fait l'objet d'un scrutin public.") == "vote"
    assert deduce.extract_ballot("Je mets aux voix cet amendement.") == "vote"
    # heard live on the simulated bench (medium model): infinitive + STT noise
    assert deduce.extract_ballot(
        "je vais mettre au voie cet amendement donc le 1305 c'est un vote à main levée") == "vote"
    assert deduce.extract_ballot("Il est rejeté.") == "rejected"
    assert deduce.extract_ballot("L'amendement est adopté.") == "adopted"
    assert deduce.extract_ballot("Ils ne sont pas adoptés.") == "rejected"
    assert deduce.extract_ballot("Quel est l'avis de la commission ?") is None


# ---- role + avis (deduced from speech, real 02/07 sentences) -----------------

def test_extract_role_real_sentences():
    assert deduce.extract_role("Merci Madame la rapporteure, votre avis ?") == (
        "rapporteur", "la rapporteure")
    assert deduce.extract_role("Monsieur le ministre.")[0] == "ministre"
    assert deduce.extract_role("Amendement 294, Madame la rapporteure.")[0] == "rapporteur"
    # a mention inside a speech is not a handoff
    assert deduce.extract_role("Je pense que la rapporteur a raison sur ce point.") is None
    # the président is thanked, not called to the mic
    assert deduce.extract_role("Oui, merci Madame la Présidente.") is None


def test_extract_avis_real_sentences():
    # «double avis X» = both benches
    assert deduce.extract_avis("Double avis favorable. Qui est pour ?") == [
        {"organe": "commission", "sens": "favorable"},
        {"organe": "gouvernement", "sens": "favorable"}]
    assert deduce.extract_avis("Monsieur le ministre, double avis défavorable, scrutin public, on vote.") == [
        {"organe": "commission", "sens": "defavorable"},
        {"organe": "gouvernement", "sens": "defavorable"}]
    # explicit organe cues, two benches diverging
    assert deduce.extract_avis("favorable de la Commission, favorable du Gouverneur.") == [
        {"organe": "commission", "sens": "favorable"},
        {"organe": "gouvernement", "sens": "favorable"}]
    # organe inferred from the current mic role (rapporteure → commission)
    assert deduce.extract_avis("Donc à titre personnel, j'ai mis un avis défavorable.",
                               speaker_role="rapporteur") == [
        {"organe": "commission", "sens": "defavorable"}]
    # no «avis» word → nothing claimed
    assert deduce.extract_avis("La CNIL a rendu un avis très sévère sur cet article 3.") == []
    assert deduce.extract_avis("Donc avis favorable.") == []  # no organe, no role


def test_deducer_emits_role_speaker_and_avis_nodes():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    d.feed(utter("amendement 1388"))  # sets the current amendment
    (rap,) = [n for n in d.feed(utter("Merci Madame la rapporteure, votre avis ?"))
              if n["kind"] == "speaker"]
    assert rap["role"] == "rapporteur"
    # the rapporteure now holds the mic → her «à titre personnel» avis is commission's
    avis = [n for n in d.feed(utter("Donc à titre personnel, j'ai mis un avis défavorable."))
            if n["kind"] == "avis"]
    assert avis[0]["organe"] == "commission" and avis[0]["sens"] == "defavorable"
    assert avis[0]["canonical"]["amendement_uid"].endswith("N001388")
    (mini,) = [n for n in d.feed(utter("Monsieur le ministre."))
               if n["kind"] == "speaker"]
    assert mini["role"] == "ministre"


# ---- agenda index (derouleur LIST as a dictionary — highlight ignored) --------

AGENDA_SNAPSHOT = {"racine": {"contenu": {"phase": [{
    "phase_libelle": "FIN DE VIE", "phase_type": "DA",
    "ligne": [
        {"id": "1", "ligne_type": "ARTICLE", "ligne_libelle_1": "ARTICLE 6",
         "ligne_video_highlighted": "true"},
        {"id": "2", "ligne_type": "ADT",
         "ligne_libelle_1": "Adt n° 1388 de M. BOVET",
         "depute_tribun_id": "793182",
         "ligne_amendement_uid": "AMANR5L17PO838901BTC2915P0D1N001388",
         "ligne_amendement_derouleur_division_ancre": "D_Article_6"},
        {"id": "3", "ligne_type": "SSADT",
         "ligne_libelle_1": "S/Adt n° 377 de M. DUPARAY",
         "depute_tribun_id": "870009",
         "ligne_amendement_uid": "AMANR5L17PO838901BTC2797P0D1N000377"},
    ]}]}}}


def test_agenda_index_lookup_by_number():
    agenda = deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT)
    e = agenda.lookup(1388)
    assert e["uid"] == "AMANR5L17PO838901BTC2915P0D1N001388"
    assert e["tribun"] == "793182"
    assert e["article"] == "D_Article_6"
    assert e["libelle"] == "Adt n° 1388 de M. BOVET"
    assert agenda.lookup(377)["tribun"] == "870009"   # sub-amendments too
    assert agenda.lookup(9999) is None                 # not on the agenda


def test_agenda_index_accumulates_across_purging_snapshots():
    """The derouleur purges discussed lines mid-sitting (verified 26/06):
    an entry seen once must survive later snapshots that no longer carry it."""
    agenda = deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT)
    later = {"racine": {"contenu": {"phase": [{"ligne": [
        {"id": "9", "ligne_type": "ADT",
         "ligne_libelle_1": "Adt n° 500 de M. NOUVEAU",
         "depute_tribun_id": "111111",
         "ligne_amendement_uid": "AMANR5L17PO838901BTC2915P0D1N000500"},
    ]}]}}}
    agenda.update(later)
    assert agenda.lookup(1388)["tribun"] == "793182"  # purged upstream, kept here
    assert agenda.lookup(500)["tribun"] == "111111"   # new line added


# ---- deducer (stateful: utterances → thread nodes) ----------------------------

ACTORS = [
    {"uid": "PA794058", "civ": "Mme", "prenom": "Justine", "nom": "Gruet",
     "groupe_uid": "PO845407"},
    {"uid": "PA123456", "civ": "M.", "prenom": "Thibault", "nom": "Bazin"},
]

ORGANES = [
    {"uid": "PO845407", "libelle": "Droite Républicaine", "libelle_abrege": "DR",
     "code_type": "GP"},
]


def utter(text, t=1000):
    return {"t": t, "seq": 0, "kind": "utterance", "state": "consolidated",
            "text": text, "source": "stt"}


def test_deducer_amendment_node_from_heard_number():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    (node,) = d.feed(utter("Alors le 1388 défendu, amendement 1388.", t=5000))

    assert node["kind"] == "amendment"
    assert node["state"] == "consolidated"
    assert node["source"] == "stt"
    assert node["t"] == 5000
    assert node["text"] == "Adt n° 1388 de M. BOVET"
    assert node["canonical"] == dict(
        deduce.EMPTY_CANONICAL,
        acteur="PA793182", tribun="793182",
        amendement_uid="AMANR5L17PO838901BTC2915P0D1N001388",
        article="D_Article_6")


def test_deducer_dedupes_amendment_but_ballots_are_events():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    assert len(d.feed(utter("amendement 1388"))) == 1
    assert d.feed(utter("sur l'amendement 1388 donc")) == []      # already woven
    (open_,) = d.feed(utter("Le scrutin est ouvert."))
    (result,) = d.feed(utter("Il est rejeté."))
    # ballots attach to the last deduced amendment (implicit subject)
    assert open_["kind"] == "ballot"
    assert open_["canonical"]["amendement_uid"].endswith("N001388")
    assert result["kind"] == "ballot"
    assert "rejet" in result["text"].lower()


def test_deducer_scrutin_result_weaves_ocr_ballot():
    """The OCR of the régie's result screen (spike) weaves a FIGURED ballot node,
    attached to the current amendment; the scrutin id resolves post-sitting."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    d.feed(utter("amendement 1388"))  # sets the current amendment
    event = {"t_ms": 1530000, "votants": 81, "exprimes": 81, "majorite": 41,
             "pour": 27, "contre": 54, "abstentions": 0, "confidence": 1.0}
    (node,) = d.feed_scrutin_result(event)
    assert node["kind"] == "ballot"
    assert node["source"] == "ocr"
    assert node["t"] == 1530000
    assert node["text"] == "Rejeté"                       # pour 27 < majorité 41
    assert node["result"] == {"votants": 81, "exprimes": 81, "majorite": 41,
                              "pour": 27, "contre": 54, "abstentions": 0}
    assert node["confidence"] == 1.0
    assert node["canonical"]["amendement_uid"].endswith("N001388")
    assert node["canonical"]["scrutin"] is None           # resolved later, off open-data


def test_deducer_scrutin_result_outcome_and_no_amendment():
    """Outcome reads the majority threshold; with no amendment heard yet the node
    still carries the figures (canonical empty)."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    (node,) = d.feed_scrutin_result(
        {"t_ms": 100, "votants": 81, "exprimes": 81, "majorite": 41,
         "pour": 55, "contre": 26, "abstentions": 0, "confidence": 1.0})
    assert node["text"] == "Adopté"                       # pour 55 >= majorité 41
    assert node["canonical"] == deduce.EMPTY_CANONICAL
    assert node["result"]["pour"] == 55


def test_scrutin_result_attaches_to_voting_amendment_not_current():
    """The figures belong to the amendment PUT TO THE VOTE («scrutin ouvert»), even
    after the chair has already called the NEXT one — real 02/07: 176 is voted, then
    «Le 310, Madame de Pélichy» moves _current to 310 right before the result screen."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("sur les deux suivants, 176 et 310, je suis saisie de scrutin public"))
    d.feed(utter("Le scrutin est ouvert."))               # 176's scrutin opens → _voting=176
    d.feed(utter("Le 310, Madame de Pellichy."))          # chair calls 310 → _current=310
    (node,) = d.feed_scrutin_result(
        {"t_ms": 1107000, "votants": 30, "exprimes": 30, "majorite": 16,
         "pour": 10, "contre": 20, "abstentions": 0, "confidence": 1.0})
    assert node["canonical"]["amendement_uid"].endswith("N000176")   # NOT 310
    assert d._current["amendement_uid"].endswith("N000310")          # context did move on


def test_deducer_speaker_resolved_fuzzily_titles_refused():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    # «Bruet» is the real STT noise for GRUET — fuzzy resolution must catch it
    nodes = d.feed(utter("L'amendement 9999, madame Bruet, défendu."))
    (speaker,) = [n for n in nodes if n["kind"] == "speaker"]
    assert speaker["canonical"]["acteur"] == "PA794058"
    assert "Gruet" in speaker["text"]
    # a bare title resolves to None → no node (honesty over coverage)
    assert d.feed(utter("Merci Madame la Présidente.")) == []


def test_deducer_speaker_carries_their_group_when_organes_known():
    """The resolved actor's groupe_uid becomes canonical.groupe, labelled from
    organes.json — the group referential of the sitting (public data)."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS,
                       organes=ORGANES)
    (speaker,) = d.feed(utter("madame Bruet"))
    assert speaker["canonical"]["groupe"] == "PO845407"
    assert speaker["groupe_label"] == "Droite Républicaine"


def test_deducer_speaker_group_absent_stays_null():
    """No organes referential, or an actor without groupe_uid: no invented group."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    (gruet,) = d.feed(utter("madame Bruet"))
    assert gruet["canonical"]["groupe"] == "PO845407"  # uid known from acteurs.json
    assert "groupe_label" not in gruet                 # but no label without organes
    (bazin,) = d.feed(utter("Monsieur Bazin."))
    assert bazin["canonical"]["groupe"] is None        # actor has no groupe_uid


def test_speaker_call_vs_mention_classification():
    """A name in a chair's call opens a turn (call=True); a name quoted inside
    a speech (real case: the minister citing «Mme Arouin-Léauté, sauf erreur»)
    is a mention — no turn break."""
    assert deduce.is_speaker_call("Monsieur Bazin.", "Monsieur Bazin")
    assert deduce.is_speaker_call(
        "Merci beaucoup madame Véronique Lundmann du groupe", "madame Véronique Lundmann")
    assert deduce.is_speaker_call(
        "L'amendement 449, madame Bruet, défendu pour la commission.", "madame Bruet")
    assert deduce.is_speaker_call(
        "La parole est à Madame Gruet.", "Madame Gruet")
    # real 02/07 demo calls: the chair often says only the amendment number
    # around the name, or asks the deputy to present/defend it.
    assert deduce.is_speaker_call("Merci. 186, Madame Catala.", "Madame Catala")
    assert deduce.is_speaker_call("Monsieur Duplessis pour le présenter.", "Monsieur Duplessis")
    assert deduce.is_speaker_call("76, madame Capdeviel.", "madame Capdeviel")
    assert deduce.is_speaker_call("L'identique, Madame Catala, le 183.", "Madame Catala")
    assert deduce.is_speaker_call("Madame Capdeviel, le 77.", "Madame Capdeviel")
    assert deduce.is_speaker_call("Le 249, M. Duplessis.", "M. Duplessis")
    assert deduce.is_speaker_call(
        "Nous en arrivons à l'article 4. Monsieur Bottorel pour le haut.",
        "Monsieur Bottorel")
    assert not deduce.is_speaker_call(
        "Donc, très ouvert à ce qu'a dit Mme Arouin-Léauté, sauf erreur.",
        "Mme Arouin-Léauté")
    assert not deduce.is_speaker_call(
        "Je rejoins la position de Monsieur Bazin sur ce point précis.",
        "Monsieur Bazin")
    assert not deduce.is_speaker_call(
        "celui de monsieur Duplessis, le 246, double avis défavorable.",
        "monsieur Duplessis")
    # real 02/07 false positive: a deputy defending amdt 176 thanks the chair
    # («Merci …») and cites a colleague («… que celui de Monsieur Duplessis») far
    # into the speech — neither the opening «Merci» nor «amendement» (a common
    # noun here) makes that mention a call
    assert not deduce.is_speaker_call(
        "Merci Madame la Présidente, il s'agit d'un amendement plus restreint "
        "puisqu'il supprime moins d'alinéas que celui de Monsieur Duplessis.",
        "Monsieur Duplessis")
    # real case (chair cutting short then calling): the name is its own
    # sentence at the END of the utterance — sentence-level start, a call
    assert deduce.is_speaker_call(
        "Je suis désolée, il faut que je tienne pour tout le monde. Monsieur David Topiac.",
        "Monsieur David Topiac")
    # but a name opening a sentence followed by discourse is NOT enough on its own
    assert not deduce.is_speaker_call(
        "C'est vrai. Monsieur Bazin a raison sur le fond du texte.",
        "Monsieur Bazin")


def test_deducer_speaker_call_can_continue_in_next_utterance():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    (mention,) = d.feed(utter("Monsieur Bazin,"))
    assert mention["call"] is False
    (speaker,) = d.feed(utter("vous vouliez reprendre la parole ?"))
    assert speaker["kind"] == "speaker"
    assert speaker["call"] == "strong"
    assert speaker["canonical"]["acteur"] == "PA123456"


def test_speaker_call_uses_previous_utterance_tail():
    """Real false positive: LocalAgreement split «…Sur la réponse pour / Mme
    Isabelle Santiago.» — the bare-name utterance CONTINUES the previous,
    unfinished sentence: a mention, not a call. With a properly closed
    previous utterance, a bare name IS a call."""
    assert not deduce.is_speaker_call(
        "Mme Isabelle Santiago.", "Mme Isabelle Santiago",
        prev_tail="une des raisons pour lesquelles... Sur la réponse pour")
    assert deduce.is_speaker_call(
        "Monsieur Bazin.", "Monsieur Bazin",
        prev_tail="Je mets aux voix cet amendement. Il est adopté.")
    assert deduce.is_speaker_call("Monsieur Bazin.", "Monsieur Bazin",
                                  prev_tail=None)


def test_deducer_mention_does_not_switch_current_speaker():
    """A mention emits a linkable node (call=False, heard kept for inline
    wrapping) but the current speaker does not change: the next real call of
    the SAME current speaker stays deduped, and a mention never blocks a
    later genuine call of the mentioned actor."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    (bazin_call,) = d.feed(utter("Monsieur Bazin."))
    assert bazin_call["call"] == "weak"   # bare-name: voice must corroborate

    (mention,) = d.feed(utter("Je partage l'analyse de madame Bruet sur ce point."))
    assert mention["call"] is False
    assert mention["heard"] == "madame Bruet"
    assert mention["canonical"]["acteur"] == "PA794058"

    # Bazin still holds the floor: naming him again in HIS OWN speech is deduped…
    assert d.feed(utter("et comme le disait Monsieur Bazin lui-même.")) == []
    # …and the real call of Gruet right after her mention still opens her turn
    (gruet_call,) = d.feed(utter("Merci. Madame Bruet, pour le groupe."))
    assert gruet_call["call"] == "strong"


def test_deducer_referentials_are_replaceable_live():
    """Sittings follow one another on the same live flow (and B4 can switch
    B2's record): actors/organes are POLLED dictionaries, replaced in place —
    B1 never restarts. After the swap, names resolve against the new set."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    assert d.feed(utter("La parole est à Monsieur Nouvel.")) == []  # unknown yet

    d.set_referentials(
        [{"uid": "PA999999", "civ": "M.", "prenom": "Jean", "nom": "Nouvel",
          "groupe_uid": "PO111111"}],
        [{"uid": "PO111111", "libelle": "Groupe Test", "libelle_abrege": "GT",
          "code_type": "GP"}])
    (node,) = d.feed(utter("La parole est à Monsieur Nouvel."))
    assert node["canonical"]["acteur"] == "PA999999"
    assert node["groupe_label"] == "Groupe Test"


def test_deducer_same_speaker_not_reemitted_until_change():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    assert len(d.feed(utter("Monsieur Bazin."))) == 1
    assert d.feed(utter("Je vous remercie Monsieur Bazin.")) == []   # still him
    assert len(d.feed(utter("madame Bruet"))) == 1                   # change
    assert len(d.feed(utter("Monsieur Bazin."))) == 1                # back again


def test_deducer_ignores_interim_and_unknown_numbers():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS)
    interim = dict(utter("amendement 1388"), state="provisional")
    assert d.feed(interim) == []
    assert d.feed(utter("l'amendement 4242 est retiré")) == []  # not on the agenda


def test_deducer_seq_shared_with_stt_weaver():
    seq = w.Seq()
    stt = w.Weaver(seq=seq)
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(AGENDA_SNAPSHOT), ACTORS,
                       seq=seq)
    (a,) = stt.feed({"type": "utterance", "beg": 1.0, "end": 2.0, "text": "amendement 1388"})
    (b,) = d.feed(a)
    assert b["seq"] == a["seq"] + 1


# ---- scrutin public + demandeur (deduced from speech, real 02/07 sentences) ----

# the derouleur pre-marks these amendments «(scrutin public)» in the libellé; the
# tribun ids/uids mirror the real 02/07 dérouleur (CATHALA/MOLAC/DUPLESSY, art. 3)
SP_AGENDA = {"racine": {"contenu": {"phase": [{"ligne": [
    {"id": "1", "ligne_type": "ADT",
     "ligne_libelle_1": "Adt n° 176 de Mme CATHALA (scrutin public)",
     "depute_tribun_id": "842187",
     "ligne_amendement_uid": "AMANR5L17PO838901B2681P0D1N000176",
     "ligne_amendement_derouleur_division_ancre": "D_Article_3"},
    {"id": "2", "ligne_type": "ADT",
     "ligne_libelle_1": "Adt n° 310 de M. MOLAC (scrutin public)",
     "depute_tribun_id": "607619",
     "ligne_amendement_uid": "AMANR5L17PO838901B2681P0D1N000310",
     "ligne_amendement_derouleur_division_ancre": "D_Article_3"},
    {"id": "3", "ligne_type": "ADT",
     "ligne_libelle_1": "Adt n° 247 de M. DUPLESSY (scrutin public)",
     "depute_tribun_id": "841351",
     "ligne_amendement_uid": "AMANR5L17PO838901B2681P0D1N000247",
     "ligne_amendement_derouleur_division_ancre": "D_Article_3"},
    {"id": "4", "ligne_type": "ADT",
     "ligne_libelle_1": "Adt n° 500 de M. NOSCRUTIN",
     "depute_tribun_id": "111111",
     "ligne_amendement_uid": "AMANR5L17PO838901B2681P0D1N000500"},
    {"id": "5", "ligne_type": "ADT", "ligne_libelle_1": "Adt n° 76 de Mme CAPDEVIELLE",
     "depute_tribun_id": "608264",
     "ligne_amendement_uid": "AMANR5L17PO838901B2681P0D1N000076",
     "ligne_amendement_derouleur_division_ancre": "D_Article_3"},
    {"id": "6", "ligne_type": "ADT", "ligne_libelle_1": "Adt n° 77 de Mme CAPDEVIELLE",
     "depute_tribun_id": "608264",
     "ligne_amendement_uid": "AMANR5L17PO838901B2681P0D1N000077",
     "ligne_amendement_derouleur_division_ancre": "D_Article_3"},
]}]}}}

SP_ORGANES = [
    {"uid": "PO845401", "libelle": "Rassemblement National", "libelle_abrege": "RN",
     "code_type": "GP"},
    {"uid": "PO845413", "libelle": "La France insoumise - Nouveau Front Populaire",
     "libelle_abrege": "LFI-NFP", "code_type": "GP"},
    {"uid": "PO845419", "libelle": "Socialistes et apparentés", "libelle_abrege": "SOC",
     "code_type": "GP"},
    {"uid": "PO845425", "libelle": "Droite Républicaine", "libelle_abrege": "DR",
     "code_type": "GP"},
    {"uid": "PO845485", "libelle": "Libertés, Indépendants, Outre-mer et Territoires",
     "libelle_abrege": "LIOT", "code_type": "GP"},
    {"uid": "PA000000", "libelle": "not a group", "code_type": "GA"},
]


def test_resolve_groupe_fuzzy_and_honest():
    assert deduce.resolve_groupe("La France Insoumise", SP_ORGANES)["uid"] == "PO845413"
    assert deduce.resolve_groupe("LFI, NFP", SP_ORGANES)["uid"] == "PO845413"
    # «Liottes» is real STT noise for LIOT — the abrégé prefix catches it
    assert deduce.resolve_groupe("Liottes", SP_ORGANES)["uid"] == "PO845485"
    assert deduce.resolve_groupe("Rassemblement National", SP_ORGANES)["uid"] == "PO845401"
    assert deduce.resolve_groupe("un groupe qui n'existe pas", SP_ORGANES) is None
    # a phrase merely STARTING with an abrégé must not resolve: «socle commun»
    # (the governing coalition) is not the Socialistes (SOC)
    assert deduce.resolve_groupe("socle commun", SP_ORGANES) is None


def test_extract_amendment_numbers_ignores_result_proclamation():
    # a result proclamation reads out the TALLY: its digits are counts, not amendments
    assert deduce.extract_amendment_numbers(
        "Résultat du scrutin, nombre de votes en 30, tous exprimés, "
        "majorité 16 pour, 10 contre 20.") == []
    assert deduce.extract_amendment_numbers("L'Assemblée n'a pas adopté.") == []
    # the guard is PER SENTENCE: an amendment call merged with a proclamation keeps
    # the amendment («… le 292. Résultat du scrutin, majorité 16 pour 10 contre 20.»)
    assert deduce.extract_amendment_numbers(
        "je mets aux voix le 292. Résultat du scrutin, majorité 16 pour 10 contre 20.") == [292]


def test_result_proclamation_weaves_no_phantom_amendment():
    """The real 02/07 misparse «Résultat du scrutin … 30 … 16 … 10 … 20» must NOT
    weave phantom amendments 30/16/10/20 (which also stole the current amendment
    from the scrutin the OCR screen is about)."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("l'amendement 310"))
    nodes = d.feed(utter("Résultat du scrutin, nombre de votes en 30, tous exprimés, "
                         "majorité 16 pour, 10 contre 20."))
    assert [n for n in nodes if n["kind"] == "amendment"] == []
    assert d._current["amendement_uid"].endswith("N000310")  # context stayed on 310


def test_extract_demandeurs_real_sentences():
    assert deduce.extract_demandeurs(
        "demandé respectivement par les groupes La France Insoumise et Liottes."
    ) == ["La France Insoumise", "Liottes"]
    assert deduce.extract_demandeurs(
        "Sur le suivant, le 247, il y a une demande de scrutin public par le groupe LFI, NFP."
    ) == ["LFI, NFP"]
    # a scrutin-public announcement with no group named: nothing to credit
    assert deduce.extract_demandeurs(
        "Je vous informe que sur les deux suivants, 176 et 310, je suis saisie de scrutin public") == []


def test_extract_demandeurs_ignores_floor_calls():
    """Only a CREDITING clause counts («par le groupe», «à la demande du groupe»).
    The membership form of a floor call («du/pour le groupe X») must never be read
    as a ballot request — this is what broke the naive gate."""
    assert deduce.extract_demandeurs("La parole est à Mme Cathala, du groupe LFI-NFP.") == []
    assert deduce.extract_demandeurs(
        "Je suis saisie. La parole est à Mme Cathala pour le groupe LFI-NFP.") == []
    assert deduce.extract_demandeurs("Je demande la parole pour le groupe LFI-NFP.") == []


def test_scrutin_public_not_fired_by_a_floor_call():
    """A chair calling a deputy «pour le groupe X» while an amendment is current
    must not fabricate a scrutin_public demandeur node (honesty over coverage)."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("l'amendement 176"))
    nodes = d.feed(utter("Je suis saisie. La parole est à Mme Cathala pour le groupe LFI-NFP."))
    assert [n for n in nodes if n["kind"] == "scrutin_public"] == []


def test_scrutin_public_demande_needs_ballot_context():
    """«à la demande du groupe X» outside a scrutin-public context (a suspension,
    a procedural request) is not a public-ballot request."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("l'amendement 500"))  # a plain amendment, no scrutin
    nodes = d.feed(utter("À la demande du groupe LIOT, la séance est suspendue."))
    assert [n for n in nodes if n["kind"] == "scrutin_public"] == []


def test_scrutin_pending_expires_after_one_utterance():
    """A parked announcement binds only to the IMMEDIATELY next utterance; a much
    later «par le groupe X» must not credit the stale amendments."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("sur les deux suivants, 176 et 310, je suis saisie de scrutin public"))
    d.feed(utter("Merci beaucoup."))                     # filler → pending expires
    d.feed(utter("l'amendement 247"))                    # current moves to 247
    nodes = d.feed(utter("Scrutin public demandé par le groupe LIOT."))
    sp = [n for n in nodes if n["kind"] == "scrutin_public"]
    # bound to the current amendment (247), NOT the stale 176/310 announcement
    assert len(sp) == 1
    assert sp[0]["canonical"]["amendement_uid"].endswith("N000247")


def test_multi_announcement_context_opens_on_first():
    """«176 et 310» announced together → the debate opens on 176 (discussed first),
    so a ballot heard next attaches to 176, not the last-named 310. Verified against
    the open-data: the first scrutin of the 02/07 pair (30/10/20) was amendment 176's."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("sur les deux suivants, 176 et 310, je suis saisie de scrutin public"))
    (ballot,) = [n for n in d.feed(utter("Le scrutin est ouvert.")) if n["kind"] == "ballot"]
    assert ballot["canonical"]["amendement_uid"].endswith("N000176")


def test_scrutin_public_credits_only_amendment_before_the_clause():
    """«…sur les 76 … par le groupe LFI-NFP. Ensuite, sur les 77 …» credits 76
    only, never the amendment that follows the clause in a merged utterance."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    nodes = d.feed(utter(
        "Il est adopté sur les 76 et identiques. Demande de scrutin public par le "
        "groupe LFI-NFP. Ensuite, sur les 77 et identiques."))
    sp = [n for n in nodes if n["kind"] == "scrutin_public"]
    uids = {n["canonical"]["amendement_uid"][-4:] for n in sp}
    assert uids == {"0076"}


def test_amendment_carries_scrutin_public_flag_from_libelle():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    (n176,) = [n for n in d.feed(utter("l'amendement 176")) if n["kind"] == "amendment"]
    assert n176["scrutin_public"] is True
    (n500,) = [n for n in d.feed(utter("l'amendement 500")) if n["kind"] == "amendment"]
    assert "scrutin_public" not in n500       # its libellé carries no marker


def test_scrutin_public_demandeur_respectivement_across_utterances():
    """«…176 et 310, je suis saisie de scrutin public» then «demandé
    respectivement par les groupes La France Insoumise et Liottes» — the follow-up
    binds group i to amendment i (176→LFI-NFP, 310→LIOT)."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    first = d.feed(utter(
        "Je vous informe que sur les deux suivants, 176 et 310, je suis saisie de scrutin public"))
    assert [n for n in first if n["kind"] == "amendment"]         # 176 + 310 woven
    assert not [n for n in first if n["kind"] == "scrutin_public"]  # no group yet

    later = d.feed(utter("demandé respectivement par les groupes La France Insoumise et Liottes."))
    sp = [n for n in later if n["kind"] == "scrutin_public"]
    assert len(sp) == 2
    by_num = {n["canonical"]["amendement_uid"][-3:]: n for n in sp}
    assert [d["groupe"] for d in by_num["176"]["demandeurs"]] == ["PO845413"]
    assert [d["groupe"] for d in by_num["310"]["demandeurs"]] == ["PO845485"]
    assert by_num["310"]["demandeurs"][0]["label"].startswith("Libertés")


def test_scrutin_public_demandeur_single_group_same_utterance():
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    nodes = d.feed(utter(
        "Sur le suivant, le 247, il y a une demande de scrutin public par le groupe LFI, NFP."))
    (sp,) = [n for n in nodes if n["kind"] == "scrutin_public"]
    assert sp["canonical"]["amendement_uid"].endswith("N000247")
    assert sp["demandeurs"] == [{"label": "La France insoumise - Nouveau Front Populaire",
                                 "groupe": "PO845413", "heard": "LFI, NFP"}]


def test_scrutin_public_unresolved_group_kept_verbatim():
    """A heard group that resolves to nothing is still credited, as heard — the
    resolver invents nothing, but the chair's word is not dropped."""
    d = deduce.Deducer(deduce.AgendaIndex.from_derouleur(SP_AGENDA), [], organes=SP_ORGANES)
    d.feed(utter("l'amendement 247"))  # set current
    (sp,) = [n for n in d.feed(utter("demande de scrutin public par le groupe Truc Machin."))
             if n["kind"] == "scrutin_public"]
    assert sp["demandeurs"] == [{"label": "Truc Machin", "groupe": None, "heard": "Truc Machin"}]


# ---- acceptance: replay the real offline transcript ----------------------------

@pytest.mark.skipif(not os.path.isdir(BUNDLE), reason="real capture bundle not mounted")
def test_real_transcript_replay_deduces_the_sitting():
    # accumulate the agenda across all snapshots — the derouleur purges
    # discussed lines, an honest live listener remembers what it has seen
    agenda = deduce.AgendaIndex()
    for path in sorted(glob.glob(f"{BUNDLE}/raw/derouleur/*.json")):
        with open(path) as f:
            agenda.update(json.load(f))
    with open(f"{BUNDLE}/referential/acteurs.json") as f:
        actors = json.load(f)

    d = deduce.Deducer(agenda, actors)
    nodes = []
    with open(f"{BUNDLE}/stt-offline-large-v3.ndjson") as f:
        for line in f:
            s = json.loads(line)
            nodes += d.feed(utter(s["text"], t=int(s["beg"] * 1000)))

    by_kind = {}
    for n in nodes:
        by_kind.setdefault(n["kind"], []).append(n)
    # the sitting's spine was deduced from speech alone
    uids = {n["canonical"]["amendement_uid"] for n in by_kind.get("amendment", [])}
    assert any(u.endswith("N001388") for u in uids), "amendment 1388 (BOVET) not deduced"
    assert any(u.endswith("N000449") for u in uids), "amendment 449 (GRUET) not deduced"
    assert by_kind.get("ballot"), "no ballot deduced despite 38 scrutin mentions"
    speakers = {n["canonical"]["acteur"] for n in by_kind.get("speaker", [])}
    assert "PA794058" in speakers, "«madame Bruet» not resolved to GRUET"
