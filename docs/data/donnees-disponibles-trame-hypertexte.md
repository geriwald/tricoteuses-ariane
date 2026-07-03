# Données disponibles pour la trame hypertexte (Ariane)

Cette note consolide l'investigation des données (issues #6, #7, #8) sous un seul angle : **quelles données sont disponibles et utiles pour réaliser la trame hypertexte en temps réel.** Tout ce qui est produit *après* le direct par l'Assemblée nationale (comptes rendus consolidés, scrutins, amendements consolidés, transcriptions différées) est écarté, **à une exception** : le flux **NVS**, conservé comme vérité terrain pour mesurer la qualité de ce qu'Ariane produit. Les faits marqués ✅ sont de lecture première main (fetch live, lecture de code/doc).

**Le critère de tri** : un flux n'est une *entrée* utile que s'il est généré par machine, en temps réel, et **ne porte pas d'attribution d'orateur**. Dès qu'un flux nomme qui parle, c'est qu'un humain l'a saisi en régie — c'est précisément la tâche qu'Ariane automatise, donc une *sortie*, pas une entrée.

Complément : le volet transcription/identification et l'historique d'investigation sont dans [le README du spike ttv](../../spikes/2026-06-23-ttv-streaming-identification/README.md) ; les décisions produit dans [le spec](../specs/2026-06-12-hyperlinked-session-thread-design.md).

## L'écosystème de données, en 4 couches

1. **Brut open data** : **27 ressources externes**, toutes des renvois (la page hackathon le dit : « toutes les ressources pointent vers des sources externes »). Répartition vérifiée par parsing du HTML réel : **13 liens `data.assemblee-nationale.fr`**, **7 `data.senat.fr`**, **3 `data.gouv.fr`** (LEGI/DOLE/JORF via DILA), **OpenFisca** (GitHub), et **6 services `tricoteuses.fr`**. ✅ Corpus entièrement **post-débat** → hors périmètre temps réel.

2. **Tricoteuses retravaillé** : les 6 services = 2 bases (`database-canutes` XIVe–XVIIe, `database-canutes-parlement` XVIIe LegiWatch), 2 API REST (`api-canutes-legifrance`, `api-parlement`), 2 MCP (`mcp-moulineuse`, `mcp-parlement`). Le Forgejo réel (`git.tricoteuses.fr`) compte **182 repos / 14 organisations** ; les outils sont dans l'org `logiciels`. ⚠️ **Anubis (anti-bot PoW) protège le Forgejo et le site (`git.tricoteuses.fr`, doc, code source), PAS les API REST de données.** Vérifié 2026-06-29 par curl nu : **`https://parlement.tricoteuses.fr` répond HTTP 200, JSON, sans auth, sans Anubis, sans MCP** — c'est une vraie API machine-to-machine (`/acteurs`, `/organes`, `/documents`, `/amendements`, `/scrutins`, résolution par `?uid=` / `?uid[]=` batch). **C'est l'accès cible pour `tricoteuses-ariane`** (un service ne peut pas dépendre d'un MCP OAuth interactif). Le MCP Moulineuse reste utile en exploration/session, mais n'est PAS une dépendance de prod. ✅

3. **Le MCP Moulineuse** : `https://mcp.code4code.eu/mcp`, transport HTTP + OAuth (scopes `moulineuse:read/sql/script/contribute`), **18 outils** en couches — recettes métier d'abord (`search_recipes`/`get_recipe`), SQL direct sur la base unifiée **`canutes`**, Typesense full-text, API Parlement read-only, génération de scripts TS, et **`add_links`** (résolution de liens via `@tricoteuses/tisseuse`). C'est le point d'entrée pour résoudre nom → ID canonique. ✅

4. **Le live (le verrou)** : ni le hackathon ni Tricoteuses ne fournissent les flux *pendant* la séance. Le live vient directement de l'AN — voir « Ce qui est disponible pendant le direct ».

## Référentiels mobilisables (stables, non live)

Moulineuse re-modélise l'open data ; il **ne réplique pas** les bases internes AN. Côté AN : **16 tables** à structure JSON (`acteurs`, `amendements`, `documents`, `dossiers`, `organes`, `reunions`, `scrutins`…). Côté Sénat : miroir fidèle d'AMELI/dosleg/sens (≈150 tables relationnelles).

Mapping des bases citées dans le défi vers la réalité Moulineuse (vérifié par `list_tables`), avec ce qui est mobilisable **pendant** la séance :

| Base citée (défi) | Réalité dans `canutes` | Utile pendant le direct ? |
|---|---|---|
| **Tribun** (acteurs) | `assemblee.acteurs` (ID `PA…`) | ✅ référentiel stable : résout l'orateur en ID canonique une fois nommé |
| **Eliasse** (amendements) | `assemblee.amendements` (+ recherche texte, signataires) | ✅ dépôt et texte connus avant séance |
| **Eloi / Legis** (textes, dossiers, séance) | `assemblee.documents` + `dossiers` + `reunions` (`odj.pointsOdj`) | ✅ ODJ et texte examiné connus |
| **scrutins** | `assemblee.scrutins` | ⚠️ à investiguer : l'**analyse consolidée** du scrutin est post-séance, mais l'**annonce** (dérouleur) et le **sort en séance** (Eliasse `sortEnSeance`) sont live. Le service des comptes rendus veut les scrutins dans la trame temps réel (CR 29 juin) → issue dédiée |
| **feuille jaune dynamique** | `points_odj` via API Parlement | partiel : donne le *sujet*, pas les inscrits nominatifs |
| **comptes rendus antérieurs** | `debats`/`interventions` (format CRI) | ❌ post-séance |
| **son / vidéo direct** | absent de `canutes` ; flux AN externe | ✅ seule donnée vraiment live, mais non structurée |

Moulineuse donne donc, en direct, le **contexte** (quel point d'ODJ, quel texte, quels acteurs) et résout les ID canoniques. Il ne donne **pas** « qui parle maintenant ».

## Ce qui est disponible pendant le direct

Le besoin temps réel n'est couvert ni par l'open data ni par Tricoteuses. Trois sources AN internes, identifiées et fetchées en direct le 2026-06-25 (séance d'amendements, PPL « mariages simulés ou arrangés »), classées par leur rôle :

| Flux | URL | Contenu | Fraîcheur |
|---|---|---|---|
| **Dérouleur** (entrée) | `www.assemblee-nationale.fr/local/derouleur/derouleur.json` | trame des amendements/articles + **ID canoniques** (`depute_tribun_id`, `ligne_amendement_uid`), scrutins annoncés, inscrits QAG (ligne `INSCRITQAG`) | JSON caché ~5 s (Varnish/ETag/304), poll 5 s |
| **Eliasse** (entrée) | `eliasse.assemblee-nationale.fr/eliasse/{prochainADiscuter,amendement,getParametresStatiques}.do` | **l'amendement courant/prochain** directement (`prochainADiscuter.do`), le `sortEnSeance` (Adopté/Rejeté/Tombé/Retiré), `etat`, auteur, cosignataires | applicatif, rafraîchi **1000 ms** |
| **NVS** (vérité terrain) | `videos.assemblee-nationale.fr/Datas/an/<direct-id>/content/data.nvs` | le sommaire réel : orateurs *effectifs*, rappels au règlement, suspensions, + ID Tribun dans `<speaker><url>` | éditorial, **saisi à la main en régie** |

Les trois rôles dans le pipeline Ariane :

| Rôle | Source | Pourquoi |
|---|---|---|
| **Entrées** (machine, temps réel, sans orateur édité) | dérouleur (UID, ODJ, inscrits QAG) + Eliasse (amendement courant + sort) + **son/vidéo** | contexte structuré, pas d'attribution humaine |
| **Sortie** (ce qu'Ariane produit) | la trame avec **qui parle**, en direct | le trou que la régie comble à la main |
| **Vérité terrain** (eval offline) | **NVS** | mesurer la qualité de la sortie Ariane |

### Les scrutins en temps réel (investigation 2026-06-29, issue #20)

Le service des comptes rendus veut les scrutins dans la trame temps réel (CR 29 juin). Décomposition de ce qui est **live** vs **post-séance**, vérifiée première main sur les captures du 25 juin :

| Élément du scrutin | Source live ? | Preuve |
|---|---|---|
| **Annonce** (« scrutin public » sur l'amendement appelé) | ✅ live, dérouleur | Capté le 25/06 : le libellé `ligne_libelle_1` de la ligne d'amendement porte `(scrutin public)` (ex. « S/Adt n° 385 de M. CADALEN (scrutin public) »). ⚠️ C'est dans le **texte du libellé**, pas (à ce stade) un champ structuré dédié → extraction par parsing du libellé, à confirmer s'il existe un champ propre. |
| **Sort en séance** (Adopté/Rejeté/Tombé/Retiré) | ✅ live, Eliasse | `record_sitting.py` capte déjà `sortEnSeance` via `prochainADiscuter.do`. |
| **Résultat chiffré + vote par député** (analyse consolidée) | ❌ post-séance | `assemblee.scrutins` — absent des flux live captés. Vérité terrain seulement, pas une entrée du tissage (comme le NVS). |

Donc un nœud `kind:"ballot"` se tisse **en direct** avec annonce + sort ; le lien vers l'analyse consolidée (nominative) se résout plus tard. Reste à trancher (#20) : champ structuré du dérouleur pour l'annonce, et si le résultat *global* (pour/contre, sans nominatif) transite par un flux live avant l'analyse consolidée.

Le NVS comme vérité terrain est **nativement daté**, donc directement exploitable pour l'éval : le `data.nvs` (chapitres + orateurs) ne porte pas de timecode, mais le fichier compagnon `liveplayer_*.nvs` mappe chaque `id` à un timecode vidéo (ms depuis `starttime`). La jointure `data.nvs.chapter.id` == `liveplayer.synchro.id` place chaque orateur sur la timeline vidéo, sans offset à mesurer. Détail des fichiers téléchargés par le player : [capture réseau du spike](../../spikes/2026-06-23-ttv-streaming-identification/artifacts/network-capture.md).

**Deux vérités terrain, complémentaires.** À côté du NVS (résumé éditorial live, daté à la grosse maille), le **CRI Syceron** est le transcript officiel **corrigé** — la référence ground-truth ultime pour l'éval, mais **post-production**. Le compte rendu intégral complet de la 17ᵉ législature (SyceronBrut) est téléchargeable en open data : `https://data.assemblee-nationale.fr/static/openData/repository/17/vp/syceronbrut/syseron.xml.zip` (~51 Mo, 558 séances ; nommage incohérent : dossier `syceronbrut` avec un `c`, fichier `syseron` avec un `s`). Structure : ID canoniques (`id_acteur`, `adt`, `art`), `ordre_absolu_seance` (la trame déjà séquencée), `code_grammaire` (nature des phases). Limite : **pas d'horodatage fin** (seulement `dateSeance` globale) → contrairement au NVS, le CRI ne se cale pas seul sur la timeline vidéo ; il sert de vérité de *contenu*, pas de *timing*.

## Latences mesurées (2 points concordants, ✅)

> ⚠️ **Séance atypique.** Le délai diffusion ↔ temps réel ci-dessous (~4 min 50 s) n'est **pas** représentatif : le délai normal est d'environ **1 minute** (vérifié avec le service des comptes rendus le 29 juin, cf. [CR de cadrage](../cadrage/2026-06-29-cadrage-tallon-raviart.md)). L'écart dérouleur ↔ vidéo (~6-7 s), lui, n'est pas mis en cause. À re-mesurer sur une séance normale.

| Repère | S/Adt 478 (Léaument) | S/Adt 540 (Amiot) |
|---|---|---|
| Vidéo (horloge diffusion) | 12:28:16 | 12:34:21 |
| Dérouleur `extract_date_time` | 12:28:10 | 12:34:14 |
| **Écart dérouleur ↔ vidéo** | **6 s** | **7 s** |
| **Délai diffusion ↔ temps réel** | **4 min 50 s** | **4 min 51 s** |

- Le **délai de diffusion** mesuré ce jour-là (~4 min 50 s) **n'est pas le délai normal** : c'est une séance atypique. **Le délai de diffusion habituel est d'environ 1 minute** (vérifié avec Xavier Tallon le 29 juin, cf. [CR de cadrage](../cadrage/2026-06-29-cadrage-tallon-raviart.md)). Ce délai, quel qu'il soit, est le **temps de production de la régie**, pendant lequel les fichiers éditoriaux (NVS) sont renseignés à la main. C'est précisément le travail qu'Ariane automatise. À re-mesurer sur une séance représentative, car ce délai dimensionne la fenêtre de causalité de la démonstration.
- Dérouleur et vidéo vivent sur **la même horloge décalée** : pour un instant donné de la timeline diffusée, l'état du dérouleur est **co-temporel** avec l'image traitée par le pipeline — pas d'offset à gérer côté dérouleur.
- Gérer le cache CDN avec un cache-buster `?modulo=<timestamp_ms>`.

## Le trou d'Ariane

Les flux d'entrée donnent le *quoi* (quel texte, article, amendement, auteur d'amendement, scrutin), ID canoniques déjà résolus pour la séance législative. **Aucun ne donne le *qui parle* à l'instant T** : auteur d'amendement ≠ personne au micro (ça peut être le rapporteur, le ministre, le président de séance, un rappel au règlement). Produire cette attribution d'orateur en direct, c'est la valeur d'Ariane.

## Accès aux sources

- Open data AN (`data.assemblee-nationale.fr`) : **bloque curl par défaut** (404) → User-Agent navigateur requis.
- `git.en-root.org` = GitLab (exige connexion) ; `git.tricoteuses.fr` et les services Tricoteuses = derrière **Anubis** → navigateur JS ou MCP, pas curl.
- Eliasse : TLS avec chaîne intermédiaire **Gandi** absente du bundle CA par défaut (d'où l'échec apparent) → pas un mur d'auth, juste `-k`/CA à ajouter ; trivial en interne AN.

## Sources (toutes vérifiées en lecture directe)

| Source | Où |
|---|---|
| Dérouleur, NVS, Eliasse | fetchés live le 2026-06-25 (séance PPL 1583) |
| Docs API officielles | `git.tricoteuses.fr/parking/tricoteuses-api-assemblee` → `docs/derouleur-api.md`, `docs/eliasse-api.md` |
| Fixtures NVS post-prod | repo `tricoteuses-transcription-videos` → `tests/fixtures/*/nvs/` |
| Liste hackathon (27 ressources) | HTML réel de la page hackathon, parsé |
| Forgejo Tricoteuses (182 repos) | HTML parsé → `forgejo.json` |
| Scripts de mesure | [`spikes/.../artifacts/scripts/watch_derouleur_nvs.py`](../../spikes/2026-06-23-ttv-streaming-identification/artifacts/scripts/watch_derouleur_nvs.py), [`record_sources.py`](../../spikes/2026-06-23-ttv-streaming-identification/artifacts/scripts/record_sources.py) |
