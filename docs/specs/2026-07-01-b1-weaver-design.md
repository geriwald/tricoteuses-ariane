---
title: "B1 — ariane-weaver (STT live) — design"
date: 2026-07-01
status: draft
supersedes: none
parent: 2026-06-26-hackathon-mockup-architecture-design.md
---

# B1 — `ariane-weaver` : STT live → `thread.ndjson` + SSE

Design du chantier B1 démarré le 2026-07-01. B1 est **la seule brique qui survit
au hackathon** (le produit). Ce document ne reprend pas le contrat inter-briques,
qui vit dans la spec d'architecture ([2026-06-26-hackathon-mockup-architecture-design.md](2026-06-26-hackathon-mockup-architecture-design.md),
§B1 et §« Thread event format ») : il n'écrit **que** les décisions propres à B1
et son périmètre de mise en œuvre. En cas de conflit, la spec d'architecture prime
pour le format d'événement et l'invariant de causalité.

## Problème

Le service des comptes rendus veut, en temps réel, une trame fiable de la séance.
Le cœur de cette trame, et le cœur de B1, c'est **« qui dit quoi »** : la
transcription live de la parole, segmentée, horodatée, et attribuée à un locuteur.
Le reste de la trame (dérouleur, amendements, scrutins) ne prend son sens qu'en
s'accrochant à ce fil parlé (décision Géraud 2026-07-01 : **on commence par le STT,
le reste ne sert à rien sans lui**).

Le spike du 2026-06-23 (`spikes/2026-06-23-ttv-streaming-identification/`) a **prouvé
la faisabilité de bout en bout** d'une chaîne STT 100 % locale et souveraine :
faster-whisper large-v3 en streaming (LocalAgreement, interim + utterance confirmée)
+ diarisation pyannote, sur la RTX 5060. Le code tourne dans `~/code/whisper-live`
(venv GPU fonctionnel). **Le chantier B1 n'est donc pas de la R&D : c'est porter ce
code prouvé en un composant qui alimente le fil `thread.ndjson`** (TDC09 : wrapper,
pas réécrire).

## Décisions actées (2026-07-01)

### D1 — La source audio est la piste son de la vidéo

En temps réel, **il n'existe pas de flux audio séparé** exposé par l'Assemblée. La
seule source disponible est **la vidéo (en léger différé de diffusion)**. Donc B1
extrait l'audio de la **piste son de la vidéo**, via `ffmpeg -i <url> -vn`.

### D2 — B1 ne connaît qu'une URL vidéo : `--source <url>`

B1 prend une **URL vidéo** en entrée et rien d'autre. Il **ignore** s'il parle au
replay ou au live : c'est ce qui réalise l'invariant du spec (« B1 ne peut pas
distinguer replay du live »). Seule l'URL change selon le mode de démo :

| Mode démo | URL vidéo `--source` |
|---|---|
| branché ariane-replay (B2) | `http://127.0.0.1:8000/video` (esclave de l'horloge maître) |
| streaming AN | le HLS Vodalys `.../master.m3u8` |
| autre direct (son seul, avant régie…) | une autre URL / device |

### D3 — Horodatage relatif uniquement : `t`, pas de `wall` absolu

Whisper produit des timecodes `beg/end` **relatifs au démarrage de ffmpeg**. B1
n'émet qu'un seul horodatage : **`t = beg * 1000`** (ms depuis le t=0 du flux).
C'est **tout ce dont le tissage a besoin** : B4 cale un nœud sur la vidéo par
`t` (= `video.currentTime`), l'ordre et le provisoire→consolidé sont sur `t`.

**Pas de `wall` absolu, pas de `--origin`** (décision Géraud 2026-07-01). Un
horodatage mural n'est **pas connaissable en live** : la vidéo est en différé de
diffusion (~1 min) et B1 se branche en cours de séance, donc « maintenant » au
lancement ne date rien de juste. Prétendre le contraire (`origin = now`) produit
un `wall` faux et trompeur. Le champ `wall` du format d'événement de la spec archi
est donc **omis** par B1 ; s'il faut un jour un mur absolu, il viendra d'une source
qui le connaît vraiment (la synchro NVS post-prod), pas d'une reconstitution B1.

### D4 — La diarisation (pyannote) est en second temps

Le premier jet émet le **STT nu** : utterances confirmées + interim, sans locuteur.
Raison honnête (TDC03) : la version du spike est **offline post-hoc** sur un WAV
complet ; la faire tourner en vrai streaming est un problème non résolu par le
spike. Le fil parlé vivant + SSE est la démonstration de base ; « qui parle »
s'ajoute ensuite. Un nœud sans locuteur porte `canonical.acteur = null` et
`canonical.tribun = null` — c'est le trou visible qu'Ariane comblera (issue #9).

### D5 — Deux passes : interim → utterance = `provisional` → `consolidated`

Le modèle deux-passes du spec (`state`, `supersedes`) est **déjà porté par le
streaming Whisper** : l'`interim` (texte non confirmé, réécrit) est un nœud
`provisional` ; l'`utterance` confirmée par LocalAgreement le **remplace**
(`supersedes`) en `consolidated`. Pas de seconde passe LLM dans ce chantier.

### D6 — Emplacement et stack

`b1-weaver/` à la racine, cohérent avec `b2-replay/`. Python. B1 **réutilise le
venv GPU de `~/code/whisper-live`** (torch cu128 + faster-whisper + le sous-module
`whisper_streaming`) plutôt que de dupliquer un stack lourd. Le port du code du
spike se limite à la boucle de streaming ; la logique de tissage (stamping `t`,
format `thread.ndjson`, SSE) est du code neuf, testé.

## Périmètre du chantier

**Scope (couche 1) :**

1. `--source <url>` → ffmpeg extrait l'audio PCM 16 kHz mono de toute URL vidéo.
2. Whisper streaming (porté de `live_whisper.py`) : interim + utterances confirmées.
3. Émission d'un **`thread.ndjson`** append-only au format §« Thread event format »
   de la spec archi : `kind: "utterance"`, `state`, `t`, `seq`,
   `supersedes`, `source: "stt"` (pas de `wall`, cf. D3).
4. Exposition d'un **flux SSE** de ce log — le contrat de sortie du produit.
   **B4 ne le consomme pas encore** : aujourd'hui B4 parle directement à B2
   (horloge, vidéo, ground-truth). Brancher B4 sur ce SSE est un chantier B4
   suivant, hors de ce chantier B1. On livre donc le SSE prêt, sans consommateur.

**Hors-scope (chantiers suivants) :**

- Diarisation pyannote (« qui parle ») — D4.
- Jointure dérouleur / Eliasse (amendements, scrutins, IDs canoniques).
- Résolution nom → ID acteur canonique PA… (issue #9).
- Passe LLM de relecture (noms propres — issue #17).
- Projection Tricoteuses (`{metadata, segments[], speakers[]}`).
- Suivi du seek de l'horloge B2 par ffmpeg (le mp4 est lu linéairement ; la démo
  de base ne seek pas pendant la transcription).

## Critères d'acceptation

- [ ] `b1-weaver` lancé avec `--source http://127.0.0.1:8000/video`
      produit un `thread.ndjson` où au moins un nœud `kind:"utterance"` porte
      `t`, `text`, `state`, `seq` (et **pas** de `wall`).
- [ ] Au moins un nœud `provisional` (interim) est **remplacé** par un nœud
      `consolidated` (`supersedes` renseigné) — la transition à deux passes.
- [ ] `t` est relatif au t=0 du flux (`t == beg * 1000`).
- [ ] Le flux SSE ré-émet chaque nœud du log ; un client qui se connecte reçoit
      les nœuds au fil de l'eau.
- [ ] B1 est **invariant à la source** : la même commande, `--source` pointant sur
      une URL live plutôt que sur B2, produit le même format sans changement de code.
- [ ] Tests pytest verts (stamping `t`/`wall`, format de nœud, `supersedes`, SSE),
      dans l'esprit TDD du repo (`b2-replay/` a déjà pytest).

## Renvois

- Format d'événement, invariant de causalité, rôle des briques : spec archi
  [2026-06-26-hackathon-mockup-architecture-design.md](2026-06-26-hackathon-mockup-architecture-design.md).
- Chaîne STT prouvée : `spikes/2026-06-23-ttv-streaming-identification/README.md`
  (§« Chemin B : Whisper local sur GPU ») et `~/code/whisper-live/`.
- Vision produit / fil hypertexte : [2026-06-12-hyperlinked-session-thread-design.md](2026-06-12-hyperlinked-session-thread-design.md).
</content>
</invoke>
