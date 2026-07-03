# Hyperlinked session thread (Ariane) — design

- **Date**: 2026-06-12
- **Status**: draft, awaiting Géraud's validation
- **Context**: Assemblée nationale hackathon, July 3-4 2026 (~30 h, restitution 3 min). Challenge drafted by the records directorate (working paper, June 3 2026); not yet published on the hackathon platform.

## Problem

During a public sitting, the information describing what is happening (phase, speaker, article, amendment under discussion, vote outcome) is scattered across several databases, partly delayed, partly never recorded at all (tributes, welcomes, unannounced speakers). Editors of the official record re-key numbers, outcomes and ballot references by hand; citizens and MPs have no live, navigable view of the sitting; the video archive has only coarse indexing.

## Product thesis

**The thread is the product.** A timestamped, append-only log of sitting events; every event carries the canonical identifiers of the AN public databases (speaker → Tribun, amendment → amendment base, text division, ballot → scrutins). All deliverables are projections of this single thread:

- live public feed of the sitting (web);
- "augmented listening" / note-taking aid for record editors, parliamentary assistants, MPs;
- fine-grained video indexing, and potentially name overlays for the broadcast;
- pre-filled skeleton of the official record (numbers, outcomes, ballots).

## Decisions

1. **Event log with canonical IDs.** Hypertext navigation falls out of the data model; no bespoke linking layer. This is a data challenge first, a UI challenge second.
2. **Two-pass analysis, visibly distinct.**
   - *Live pass*: fast, lightweight STT feeding the thread and enrichment processes in near real time.
   - *Delayed pass*: stronger STT, diarization, LLM proofreading (homophones, misheard acronyms); consolidated results **replace** provisional segments in the thread.
   - Segment state is visible in the UI (e.g. greyed text until consolidated). Trust argument: the system shows what it knows and what it does not know yet.
3. **Replay-based demo.** True live capture is a product goal, not a hackathon goal. Complete videos of past sittings are downloaded in advance; each recording is paired with its **aligned dataset** (official record, amendments and outcomes, ballots, expected agenda). The recording + dataset couple is what makes the challenge playable. At restitution, observers pick the sitting from the catalog (no-rigging proof). Nice to have: replay straight from the AN video-on-demand portal (fully free choice).
4. **Speaker identification by multi-cue matching, no biometrics.** Cues: audio, expected agenda (feuille jaune), session context; simple video cues (shot changes correlate with speaking turns; framing class: rostrum, chair, government bench). Facial recognition is explicitly out of scope (biometric processing).
5. **AI focused where the databases are silent.** Unlisted phases (tribute, welcome, announcement) detected by an LLM calibrated on the corpus of past records; unannounced speakers via cue matching. Everything the databases already state is ingested, not inferred.
6. **Reversed banner.** The broadcast appears to carry no speaker name overlay today (checked 2026-06-12, to be confirmed). The thread, which knows who is speaking at every instant, can *provide* that overlay: an output, not an input.
7. **Sovereignty / data positioning.** Consume a trusted data layer (AN open data, possibly the Tricoteuses cleaned datasets or the MCP endpoint announced for the hackathon); expose the thread itself as a normalized, reusable feed (API, possibly MCP), agnostic of the consumer.

## Acceptance criteria (hackathon scope)

- [ ] Replaying an observer-chosen sitting from the catalog builds the thread on screen as the recording plays.
- [ ] Every event links to its canonical record (Tribun sheet, amendment, ballot analysis).
- [ ] At least one unlisted phase (e.g. a tribute) is detected and inserted by the LLM pass.
- [ ] At least one speaker is identified from sound + context without biometrics.
- [ ] Provisional vs consolidated segments are visually distinct, and a delayed-pass correction is shown replacing a live-pass error.

## Open questions

- Does upstream "who has the floor / which microphone is open" data exist and is it accessible? If so, speaker identification is solved at the source in production.
- ~~Is the dynamic feuille jaune available outside the walls, or can an export be provided per reference sitting?~~ **Resolved 2026-06-24** (Emmanuel Raviart, WhatsApp): the dynamic *jaune*, including the list of MPs registered for questions to the Government, is NOT in the open data but is exposed by the AN real-time **dérouleur** API — page `https://www.assemblee-nationale.fr/dyn/seance-publique/derouleur`, raw JSON `https://www.assemblee-nationale.fr/local/derouleur/derouleur.json` (callable directly with the usual API-politeness precautions). Tricoteuses doc (in progress): `https://git.tricoteuses.fr/parking/tricoteuses-api-assemblee/src/branch/master/docs`. **Verified by fetch 2026-06-25**: real-time JSON, carries `depute_tribun_id` (canonical actor ID) + `ligne_amendement_uid` (Eliasse) on 355/357 lines, plus a live `ligne_video_highlighted` cursor — so the amendment dérouleur resolves much of the canonical-ID weaving upstream. The QAG-registrants view is a separate projection of the same API, still to fetch on a QAG day.
- Do hackathon rules allow advance preparation (data schemas, downloaded recordings, tooling)?
- Internal prior art on transcription (multi-year speech-to-text project): inherit what?
- ~~Product name: "Ariane" proposed, alternatives listed in the project sheet; decision pending.~~ **Resolved 2026-06-24: "Ariane".**

## Decisions update (2026-06-24, after exchange with Emmanuel Raviart)

- **Name: Ariane** (confirmed, both sides preferred it over `tricoteuses-trame-hypertexte`).
- **Positioning: a new Tricoteuses project** named `tricoteuses-ariane` (AGPL), joining the Tricoteuses org rather than staying an independent consumer. Emmanuel raised no objection — on the contrary. This supersedes the "possibly the Tricoteuses datasets / MCP endpoint" wording of decision 7: Ariane *is* a Tricoteuses maillon, consuming their APIs (parlement, dérouleur, Eliasse) and producing the thread.
- **Live speaker-source: the dérouleur API** (see resolved open question above) is the live replacement for the post-production NVS candidates — the missing piece of the spike. Feeds the multi-cue matching of decision 4.
- **Output format:** align on what `tricoteuses-transcription-videos` produces and on the **syceron / syseron** Compte-Rendu format, by default.
- **Two deliverables:** (1) a real-time audio "tricotage" script producing the thread; (2) a web app displaying the clickable thread.

## Decisions update (2026-06-29, meeting with Xavier Tallon + Emmanuel Raviart)

Records directorate (Xavier Tallon) meeting — see [cadrage note](../cadrage/2026-06-29-cadrage-tallon-raviart.md). The service confirms and widens the product thesis:

- **The need is broader than transcription.** The service wants the live **dérouleur**,
  the **amendments** and the **scrutins** in the thread, not just "who is speaking".
  This confirms the "event log with canonical IDs" thesis directly from the customer.
- **Scrutins are an in-scope source, not just post-production.** They must appear in the
  real-time trame. (Investigation: the dérouleur *announces* ballots and Eliasse carries
  `sortEnSeance`; the consolidated ballot analysis stays post-production — see data doc.)
- **The three target uses, confirmed by the service** (they map onto the thesis projections):
  live search + video replay at an instant (MP / general public); note-taking aid for
  record editors; **name/scrutin/text overlays incrusted on the AN broadcast** (subtitles,
  speaker name, text under discussion). The last two are "pourquoi pas" leads, not commitments.
- **AN green light on a voice-signature base.** The Assemblée agrees to constitute a base of
  tribun voice signatures for speaker identification. No RGPD blocker at hackathon stage, but
  flagged as a point to clarify legally (a persistent voice print is biometric data — this
  refines decision 4 / out-of-scope biometrics: contextual cues for the demo, voice-signature
  base as a documented, RGPD-gated product option).
- **Régie technical signals are not exploitable** (open microphones, etc.) — not a source.
- **Existing internal prior art: "ttv" (author Pierre Drège), demoed by Emmanuel.** Already
  covers part of the function; **mutualize post-hackathon** rather than rebuild (TDC09). This
  is the internal transcription prior art the June-12 open question asked about.
- **Broadcast delay ~1 min, not ~4 min 30.** The 4 min 30 seen on Friday was atypical
  (confirmed together Monday). This corrects the spike measurement (~4 min 50 s, 25 June, an
  atypical sitting) and matters for the causality window — see data doc.

## Out of scope

- True live capture in the hemicycle (product phase, not hackathon).
- Facial recognition / any biometric processing.
- Automated assembly of the JORF booklet (separate challenge, separate team).
- Production deployment on AN infrastructure.

## References

- Project sheet: `../cadrage/hackathon-assemblee-2026.md`
- Meeting note (June 17 2026): `../cadrage/note-pour-reunion-2026-06-17.md`
- Challenge source: `../cadrage/Document de travail hackathon.docx` (records directorate, June 3 2026)
