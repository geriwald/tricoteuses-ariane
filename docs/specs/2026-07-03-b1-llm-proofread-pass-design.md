---
title: "B1 — LLM proofread pass (issue #17) — design"
date: 2026-07-03
status: validated (Géraud, 2026-07-03 — option D + re-segmentation D8 actées après éval)
parent: 2026-07-01-b1-weaver-design.md
---

# B1 — passe LLM de relecture : corriger le texte STT après résolution

Dernier étage de la fusée B1. Le spike du 2026-06-23 a montré que les erreurs
STT sur noms propres et acronymes (« Someni » pour Somaini, « Bruet » pour
Gruet, « je mets au voie ») ne sont **pas un problème d'intelligence du modèle
mais d'information** : la valeur est « LLM **+ données canoniques** », pas
« LLM vs STT ». Cette passe donne au LLM la liste résolue de la séance et lui
fait corriger le *texte* des utterances — pas l'attribution des locuteurs, qui
vient déjà du référentiel sans LLM.

Assumé **quick and dirty** (décision Géraud 2026-07-03) : l'appel passe par le
CLI `claude` local sur caladan (abonnement), pas par l'API. Le contrat
d'entrée/sortie est propre ; le transport est jetable.

## Position dans la pipeline

```
STT streaming ──► [2e passe Whisper — n'existe pas encore] ──► deduce/resolve_id ──► LLM proofread
(utterances)                                                    (IDs canoniques)     (texte corrigé)
```

L'étage consomme les nœuds `utterance` **`consolidated`** (jamais les interim)
et émet des nœuds `utterance` corrigés, `source: "llm"`,
`state: "consolidated"`, `supersedes: <seq du nœud source>` — le format
d'événement de la spec archi le prévoit déjà (`source: "stt|derouleur|eliasse|nvs|llm"`).
Il doit fonctionner que la 2e passe Whisper existe ou non : il se branche sur
« ce qui est consolidé aujourd'hui ».

## Décisions

### D1 — Le contexte canonique est la liste résolue de la séance, rien de plus

Le prompt embarque les acteurs de `referential/acteurs.json` (le même fichier
que `resolve_id`), rendus en lignes compactes `Civ Prénom Nom`. Quelques
dizaines de lignes pour une séance — pas les 3115 acteurs de la base, pas de
JSON brut. S'y ajoute un petit glossaire d'acronymes AN (PPL, CMP, QAG, CRA…),
statique, versionné avec le prompt.

### D2 — Interdiction d'inventer (transposition de TDC03 au prompt)

Si aucun candidat ne matche avec confiance, le modèle laisse le texte tel quel
et signale le passage douteux (`flags` dans sa sortie). Une correction
hallucinée est pire qu'une erreur STT visible. Même philosophie que
`resolve_id` : « honesty over a wrong ID ».

### D3 — Appels isolés par fenêtre, pas de conversation suivie

- Fenêtre de **20 utterances consolidées**, chevauchement de **2** pour la
  continuité discursive ; flush sur timeout (30 s sans nouvelle utterance).
- Chaque appel est **stateless** : préambule statique (consigne + candidats +
  glossaire) + la fenêtre. Parallélisable, rejouable, retry trivial.
- Pas de `--resume`/conversation : le contexte utile est statique, et une
  session suivie gonflerait sans borne sur une séance de plusieurs heures.

### D3bis — Le contrat est par `seq` : la passe ne touche jamais à la segmentation

La fenêtre est envoyée comme **liste numérotée** `[seq] texte`, et la sortie
référence ces `seq` un par un. Le modèle corrige *à l'intérieur* d'une
utterance ; fusionner ou scinder est interdit et rejeté par le parseur. Il n'y
a donc **aucun redécoupage** de la sortie LLM : l'alignement `supersedes` est
garanti par construction. Conséquence assumée (TDC03) : un mot coupé à cheval
sur deux utterances (artefact de frontière de chunk STT) n'est pas réparable
ici — c'est le travail de la 2e passe Whisper, en amont (hors-scope).

### D4 — Modèle : Sonnet, avec indices difflib injectés (révisé après éval, option D)

Le plan initial (Haiku) est tombé à l'éval du 2026-07-03 (runs réels, séance du
26/06, 40 utterances, 136 candidats) : Haiku corrige les coquilles
(« au voie » → « aux voix », 3/3) mais **rate le match flou d'un nom contre la
liste** (« Bruet » → Gruet raté deux fois, prompt renforcé entre les deux —
flaggé « aucun candidat » alors que Gruet est dans la liste). Sonnet réussit
tout, latence CLI comparable.

Décision (Géraud, option D) : **`claude -p --model sonnet` par défaut**, et le
prompt embarque des **indices de résolution** calculés en amont — les noms
détectés par `deduce.extract_speaker_names` sont résolus par
`resolve_id.resolve` (difflib, déjà testé, résout « Bruet » → Gruet à 0.80) et
injectés en `«entendu» → suggestion : Nom canonique (score)`. Le travail flou
est fait par du code déterministe ; le LLM confirme en contexte. Un indice
« aucun candidat proche » renforce D2 : flagger, ne pas corriger.

### D5 — Sortie JSON stricte, parsée et validée

Le modèle répond un JSON : liste de `{seq, text_corrected, changes[], flags[]}`
pour les seules utterances modifiées ou flaggées. Le parseur rejette tout écart
(JSON invalide, seq inconnu, texte vide) → la fenêtre est ignorée, les nœuds
source restent tels quels, l'erreur est loggée. Un étage de relecture ne doit
jamais pouvoir *casser* le fil.

### D6 — Emplacement

`b1-weaver/proofread.py` (cœur pur, testé : fenêtrage, prompt, parsing,
génération des nœuds `supersedes`) + le transport CLI isolé derrière une
fonction injectable (mockée dans les tests). Prompt dans
`b1-weaver/prompts/proofread.md`, versionné.

### D8 — Re-segmentation : un nœud peut superséder plusieurs seq (révise D3bis)

D3bis interdisait de toucher au découpage (contrat strict par seq). L'éval du
2026-07-03 l'a invalidé : le STT coupe **13 % des utterances en plein milieu**
d'une phrase (mesuré sur la séance du 26/06), et ces coupures bloquaient des
corrections. **D3bis est levée.**

Le LLM reçoit un paragraphe et renvoie le transcript corrigé **une prise de
parole par ligne**, libre de **fusionner** les fragments qu'une phrase traverse.
Un `realign` déterministe (union-find des lignes partageant un seq, testé)
rattache chaque segment corrigé à l'**ensemble des seq** qu'il couvre. Le nœud
émis porte alors `supersedes: [seq, …]` (liste) et hérite du **`t` le plus
précoce** des seq couverts (début de la prise de parole sur la vidéo). Deux
garde-fous : une ligne ne couvrant aucun seq d'origine (invention pure) est
ignorée ; un seq entièrement supprimé par le modèle est **laissé tel quel**,
jamais escamoté (préservation du contenu).

Consommateurs de `supersedes` mis à jour : B4 (`b4-ui/index.html`) normalise
`supersedes` en liste, remplace la première ligne supersédée et retire les
autres.

**Liberté de réécriture assumée (validée Géraud 2026-07-03).** Le modèle peut
re-rattacher les nombres à leurs étiquettes dans un décompte de scrutin mal
transcrit (« 32 pour, 23 contre » → « majorité 32, pour 23 ») et restructurer
la ponctuation/le découpage du sens. Ces libertés ont été examinées sur cas
réels et jugées **correctes** : on privilégie la lisibilité d'un compte rendu
propre. La règle « ne jamais inventer un nom hors candidats » (D2) reste, elle,
absolue.

## Hors-scope

- La 2e passe Whisper sur chunks recollés (fonction 2 — chantier séparé) ;
  note : D8 répare déjà les noms coupés à une frontière de fragment par fusion.
- La signature des voix (fonction 1 — non spécifiée à ce jour).
- Le lexique de corrections inter-fenêtres (« Someni → Somaini » mémorisé et
  réinjecté) — v2 si l'éval montre des incohérences entre fenêtres.
- Re-nourrir `deduce`/`resolve_id` avec le texte corrigé (boucle de rétroaction).
- Le passage à l'API Anthropic (prod) : le contrat D5 rend le transport
  interchangeable.

## Critères d'acceptation

- [x] Sur un extrait réel de la capture FIN DE VIE, la passe corrige au moins
      un nom propre massacré par le STT en s'appuyant sur la liste résolue,
      et émet le nœud `source: "llm"` + `supersedes` correspondant.
- [x] Un nom absent de la liste des candidats n'est **jamais** « corrigé » :
      texte inchangé, flag émis (« Someni » flaggé, jamais réécrit — runs 1-3).
- [x] Une sortie LLM invalide (JSON cassé, seq inconnu) ne produit aucun nœud
      et ne casse pas le fil (erreur loggée, fenêtre ignorée) — testé.
- [x] Le fenêtrage est déterministe : mêmes utterances → mêmes fenêtres
      (taille 20, chevauchement 2, flush timeout) — testé.
- [x] Tests pytest verts (20), transport CLI mocké ; run réel documenté
      ci-dessous.

## Run d'acceptation (2026-07-03, caladan)

Entrée : `stt-offline-large-v3.ndjson` de la capture `2026-06-26-evening`
(séance FIN DE VIE), converti en nœuds `utterance/consolidated`, 40 premières
utterances (2 fenêtres), candidats = `referential/acteurs.json` (136 acteurs).

```bash
python b1-weaver/proofread.py --thread thread-2026-06-26.ndjson \
    --actors .../2026-06-26-evening/referential/acteurs.json --limit 40
```

Résultat (Sonnet + indices, 60 s) : 5 nœuds `source: "llm"` émis, dont
« je mets **au voie** le 1388 » → « je mets **aux voix** le 1388 » (×3) et
« L'amendement 449, madame **Bruet** » → « madame **Gruet** » (le cas
canonique du spike). Chiffres intacts partout (règle 4). Comparaison des
modèles : Haiku seul ratait Bruet→Gruet (2 runs) ; Sonnet sans indices le
trouvait en réanalysant l'arithmétique du scrutin ; Sonnet + indices le trouve
directement et sans flag parasite.
