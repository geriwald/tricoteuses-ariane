# Capture réseau d'une séance live (que télécharge le player AN ?)

- **Date** : 2026-06-26
- **Séance** : « 2ème séance : Fin de vie (nouvelle lecture) (suite) »
- **`direct-id`** : `19247568_6a3e745b41c23` (change à chaque diffusion ; il est dans l'URL `videos.assemblee-nationale.fr/direct.<ID>`)
- **Méthode** : fetch direct des endpoints (UA navigateur + Referer), puis descente du manifeste HLS. Tous les chiffres ci-dessous sont de **lecture** (réponses HTTP réelles), sauf mention.

## Inventaire des fichiers téléchargés

| # | Fichier | Hôte | Format | Rôle | Cadence |
|---|---|---|---|---|---|
| 1 | `direct.<ID>` | `videos.assemblee-nationale.fr` | HTML (33 Ko) | la page du player | 1× au chargement |
| 2 | `derouleur.json` | `www.assemblee-nationale.fr/local/derouleur/` | JSON (244 Ko) | trame amendements/articles + ID canoniques (Tribun, Eliasse) | poll ~5 s, caché |
| 3 | `data.nvs` | `videos.assemblee-nationale.fr/Datas/an/<ID>/content/` | XML propriétaire (50 Ko) | arbre des chapitres : sujets, **orateurs effectifs**, ID Tribun | re-fetch périodique (`?modulo=<ms>`) |
| 4 | `liveplayer_<epoch>.nvs` | idem `/content/` | XML propriétaire (15 Ko) | **piste de synchro** : `id → timecode` (ms) | re-fetch (nom = epoch, change) |
| 5 | `index36_<ID>.m3u8` + `stream36_{1,2,3}_<ID>.m3u8` | `anorigin.vodalys.com/live/live36/` | HLS (M3U8) | manifeste vidéo : 3 variantes (2/4/0,5 Mbps) | master 1×, variante re-poll |
| 6 | `media_2_<ID>_<n>.ts` | idem Vodalys | MPEG-TS (~5-6 Mo) | segments vidéo (10 s chacun) | 1 toutes les ~10 s ; **fenêtre DVR ≈ 1523 segments** |

Storyboards (`./files/storyboard/<sec>.jpg`) référencés dans le `data.nvs` post-prod, mais le chemin testé renvoie 404 en live → emplacement réel à confirmer (non bloquant).

## Observations

1. **Deux infrastructures, deux propriétaires.** Le *portail et les données éditoriales* (HTML, dérouleur, NVS) sont sur les domaines **`assemblee-nationale.fr`**. La *vidéo* (HLS master, variantes, segments `.ts`) est servie par **Vodalys** (`anorigin.vodalys.com`), prestataire vidéo de l'AN. Le format `.nvs` est propriétaire Vodalys ; son contenu (chapitres, orateurs) est rempli par la régie AN.

2. **Les deux fichiers NVS ont des rôles séparés** (point clé) :
   - `data.nvs` = **quoi/qui** (chapitres, orateurs, ID Tribun dans `<speaker><url>`), **sans aucun timecode** ;
   - `liveplayer_*.nvs` = **quand** (`<player starttime=…><synchro id=… timecode=…>`, timecode en **ms** depuis `starttime` epoch).
   - On les **joint par `id`** (`data.nvs.chapter.id` == `liveplayer.synchro.id`) pour dater chaque orateur sur la timeline vidéo. Sur ce run : 244 synchros = ~229 vignettes storyboard (pas régulier de 60 000 ms) + **15 vraies transitions** de chapitre/orateur (timecodes irréguliers).

3. **La vidéo est en DVR.** Le manifeste liste ~1523 segments de 10 s → une fenêtre glissante d'environ 4 h rejouable. Les segments `.ts` sont le flux que le pipeline ttv consomme.

4. **Cadences distinctes** : dérouleur ~5 s (caché Varnish), segments vidéo ~10 s, NVS re-fetché avec cache-buster `?modulo=`. Le NVS éditorial est saisi à la main en régie → c'est la **vérité terrain**, pas une entrée (cf. [docs/data](../../../docs/data/donnees-disponibles-trame-hypertexte.md)).

## Reproduire la capture

```bash
DID=<direct-id du jour>   # dans l'URL videos.assemblee-nationale.fr/direct.<ID>
C=https://videos.assemblee-nationale.fr/Datas/an/$DID/content
# données éditoriales
curl -s "https://www.assemblee-nationale.fr/local/derouleur/derouleur.json?modulo=$(date +%s%3N)" -o derouleur.json
curl -s "$C/data.nvs?modulo=$(date +%s%3N)" -o data.nvs
# liveplayer : nom = liveplayer_<epoch>.nvs (le repérer dans l'onglet réseau)
# vidéo HLS (master -> variantes -> segments)
curl -s "http://anorigin.vodalys.com/live/live36/index36_${DID%%_*}.m3u8?DVR"
```

Le `watch_derouleur_nvs.py` du spike fetche déjà dérouleur + `data.nvs` ; il ne lit pas encore le `liveplayer` (timecodes) ni le HLS.
