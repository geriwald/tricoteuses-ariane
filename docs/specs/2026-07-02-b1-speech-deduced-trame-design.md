---
title: "B1 — speech-deduced trame (deduce events from STT, resolve via referentials)"
date: 2026-07-02
status: draft (written under delegation, night of 02→03/07; Géraud to ratify)
parent: 2026-07-01-b1-weaver-design.md
---

# B1 — la trame déduite de la parole

> **Invariant produit (non négociable).** Ariane **remplace la régie** : le fil se
> déduit de la parole. Tout ce qu'une main de régie saisit en live (surbrillance
> du dérouleur, NVS live) est **interdit comme source du fil** — au mieux un
> étalon d'éval. Les listes publiques (ordre du jour du dérouleur, acteurs,
> Eliasse) ne servent que de **dictionnaires** pour traduire ce qui a été
> *entendu* en IDs canoniques. Toute nouvelle source doit répondre à : « Ariane
> l'a-t-elle déduit de la parole, ou copié du travail d'un humain ? »

## Problème

Le fil actuel est un sous-titrage : des utterances sans IDs. Le produit (#9, #10)
est le fil *hypertexte* : la parole reliée aux amendements, orateurs et scrutins
canoniques — déduits de l'écoute, comme le fera le service des comptes rendus.

## Ce que dit le réel (lu dans `stt-offline-large-v3.ndjson`, 423 segments, séance du 26/06)

- **« La parole est à … » : 0 occurrence.** En examen des amendements, la
  présidence appelle par le nom : « Monsieur Bazin. », « L'amendement 449,
  madame Bruet, défendu », « Je vous remercie Monsieur Bazin ».
- **Les numéros d'amendement sont fiables** (chiffres STT) : « amendement 1240
  n'est pas défendu », « je mets aux voix le 1388 », « sur les amendements 1242
  et 1388 ». **Les noms propres sont massacrés** : « Bruet » (GRUET), « Juvain »
  (JUVIN) → la voie robuste est le numéro ; le nom se résout en flou.
- **Scrutin/vote** : « Le scrutin est ouvert. », « je mets au voie [sic] le
  1388 », « Il est rejeté. » — fautes STT à tolérer, sujet implicite (le dernier
  amendement mentionné).

## Décisions

### D1 — Les événements se déduisent des utterances consolidées

Le Deducer consomme les nœuds `utterance` `consolidated` (pas les interim : trop
instables) et émet des nœuds `amendment` / `speaker` / `ballot`, `source: "stt"`,
`state: "consolidated"`, `t` hérité de l'utterance déclencheuse.

### D2 — Trois détections, calibrées sur le transcript réel

1. **Numéros d'amendement** : `amendement(s) [n°|numéro] <num>` et les numéros
   nus en contexte amendement dans la même phrase (« je mets aux voix le 1388 »).
2. **Appels d'orateur** : `(M.|Mme|Monsieur|Madame) <Nom>` ; les titres seuls
   (« Madame la Présidente ») sont éliminés par le résolveur (→ None, D3).
3. **Scrutin/vote** : ouverture (« scrutin est ouvert »), mise aux voix (« mets
   au(x) voi(x|e) »), résultat (« est adopté / est rejeté / ne sont pas adoptés »).

### D3 — Résolution par dictionnaires publics uniquement

- **Numéro → uid/auteur/article** : l'**ordre du jour** du `derouleur.json` — la
  *liste* des lignes, en ignorant tout marqueur régie. Chaque ligne ADT/SSADT
  donne `ligne_amendement_uid` (le numéro y est encodé, `N%06d`),
  `depute_tribun_id`, et l'ancre de division (`D_Article_6` → `canonical.article`).
- **Nom flou → PA** : `resolve_id.resolve(name, actors)` contre `acteurs.json`
  (déjà spécifié/testé, seuil + refus d'ambiguïté, TDC03 : jamais de faux positif
  silencieux).

### D4 — Deducer stateful : le contexte est le dernier amendement déduit

Les nœuds `ballot` portent le `canonical` du dernier amendement mentionné (c'est
le sujet implicite de « Il est rejeté »). Un numéro déjà déduit n'est pas réémis
(déduplication par uid), sauf pour les ballots qui, eux, sont des événements.

### D5 — Branchement live, mêmes invariances

`deduce.py` pur (aucun réseau). `weaver_live.py` : chaque utterance confirmée
passe au Deducer après émission. Options : `--agenda <url>` (le `derouleur.json`,
re-fetché ~30 s car l'ordre du jour s'allonge en séance — usage liste seule) et
`--actors <url>` (fetch au démarrage). URLs = vrai AN ou mock B2, B1 ne sait pas.

## Critères d'acceptation

- [ ] Rejouer les 423 segments offline du 26/06 avec l'agenda du bundle déduit :
      l'amendement 1388 (BOVET, `PA793182`), le 449 via « madame Bruet » résolue
      GRUET, des ballots ouverts/résultats rattachés au bon amendement.
- [ ] Un titre seul ne produit aucun nœud speaker ; un numéro hors agenda ne
      produit aucun nœud amendment (honnêteté > couverture).
- [ ] Nœuds au format du fil (kind/canonical/source/state/t), `seq` partagé.
- [ ] pytest vert (`test_deduce.py`, fixtures = phrases réelles du transcript).
- [ ] Bout en bout : B1 sur le banc HLS live simulé + agenda B2 → des nœuds
      déduits visibles dans B4 (brut).

## Hors scope (crans suivants)

- Diarisation, déduction sur interim (nœuds `provisional` + `supersedes`).
- Passe LLM #17 (corriger les noms propres avant résolution).
- Éval chiffrée contre l'étalon régie (`trame.py`, eval-only) et le NVS post-prod.
- Articles déduits directement (« Sur l'article 7 ») — l'article vient pour
  l'instant de l'ancre de l'amendement résolu.
