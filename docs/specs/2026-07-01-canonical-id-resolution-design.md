---
title: "Canonical ID resolution — detected name → PA<tribun> (issue #9)"
date: 2026-07-01
status: draft
parent: 2026-06-26-hackathon-mockup-architecture-design.md
---

# Résolution des ID canoniques : nom détecté → `PA<tribun>` (issue #9)

Le trou qu'Ariane comble (issue #9) : le STT produit un **nom** (l'orateur, annoncé
par le président ou détecté), les bases veulent un **ID canonique**. Ce document
cadre la brique qui fait le pont **nom → uid acteur** et le **test** qui le mesure.

## Problème

Le STT sort des chaînes-noms bruitées (« Monsieur Jean Dupont », « madame Catherine
X », erreurs phonétiques sur les noms propres — le spike a montré « Somaini » →
« Someni »). On veut en tirer l'`uid` canonique de l'acteur (`PA<tribun_id>`), qui
ouvre ensuite tout l'hypertexte (groupe, amendements, votes).

## Ressources (lues, vérifiées)

- **`referential/acteurs.json`** : liste d'acteurs de la séance, chacun
  `{uid: "PA266797", civ, prenom, nom, slug, groupe_uid}`. `uid = "PA" + tribun_id`
  (le pont #9, établi dans `resolve_referential.py`). Taille : ~49-136 par séance.
- **Vérité terrain `data.nvs`** : `<name>Mme Perrine Goulet</name>` + `<url>720560</url>`.
  Chaque nom effectif y est apparié à son tribun_id → sert à **mesurer** la justesse
  d'un match (le bon `uid` est `PA` + `<url>`). Non causal (post-prod), eval only.

## Décisions

### D1 — Cible : le set d'acteurs de la séance, pas tout l'AN (pour commencer)

Au moment de la démo, les orateurs candidats sont les **attendus de la séance**
(dérouleur / participants), ce que `acteurs.json` approxime. On résout donc contre
ce set (~50-140 acteurs), pas les ~925 acteurs AN. Plus petit = moins de collisions,
et c'est la vraie contrainte live. Scaling au set complet : hors scope initial.

### D2 — Normalisation avant match

Des deux côtés (requête et candidats) : minuscules, **suppression des accents**
(`unicodedata` NFKD), **retrait de la civilité** (M./Mme/Monsieur/Madame/…),
espaces normalisés. Un nom candidat = `"prenom nom"` normalisé.

### D3 — Matching flou + confiance, jamais de faux positif silencieux

Score = combinaison (ratio `difflib` sur le nom complet normalisé, priorité au
**nom de famille**). On renvoie `(uid, score)` ; **`None` si sous le seuil** ou si
**ambigu** (deux candidats trop proches, ex. deux « Martin » sans prénom). Un titre
seul (« Monsieur le Président ») n'a pas de nom → `None`. On préfère avouer
l'incertitude (TDC03) plutôt qu'attribuer un mauvais ID.

### D4 — Résolveur pur, testable, séparé du live

`resolve_id.py` : pur (pas de GPU, pas de réseau), `resolve(name, actors) ->
{uid, score} | None`. Le branchement sur le flux STT live (extraire les noms du
texte, appeler le résolveur, estampiller les nœuds) est un cran ultérieur.

## Test / eval (le cœur de ce chantier)

`eval_resolve_id.py` mesure sur données réelles :
1. **Baseline noms propres (NVS)** : chaque `<name>` propre du NVS → `resolve` →
   comparer l'`uid` obtenu à `PA + <url>`. Mesure la borne haute (noms bien formés).
2. **Robustesse au bruit STT** : dégrader les noms NVS (retrait civilité, erreurs
   phonétiques/accents simulées) → re-mesurer. C'est le vrai chiffre qui compte.
Sortie : précision, rappel, taux d'ambiguïté, liste des échecs (pour itérer).

## Critères d'acceptation

- [ ] `resolve()` renvoie le bon `uid` sur un nom propre exact du set, civilité
      retirée, insensible aux accents/casse.
- [ ] Un titre seul et un nom absent renvoient `None` (pas de faux positif).
- [ ] Un nom de famille ambigu (deux acteurs) sans prénom renvoie `None`/ambigu.
- [ ] Une erreur phonétique légère sur le nom se résout quand même (flou).
- [ ] `eval_resolve_id.py` tourne sur un bundle réel et sort un chiffre de précision
      sur les noms NVS, propres puis dégradés.
- [ ] Tests pytest verts (normalisation, exact, flou, ambigu, absent, titre).

## Hors scope (crans suivants)

- Extraction des noms depuis le texte STT libre (« la parole est à … ») — NER/patterns.
- Résolution contre le set complet AN (~925) + désambiguïsation par groupe/contexte.
- La passe LLM #17 (corriger le nom propre mal transcrit *avant* de résoudre).
- Le branchement live (estampiller les nœuds `thread.ndjson` avec l'uid résolu).
