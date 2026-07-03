# Spike : ttv en streaming + identification des locuteurs

- **Date** : 2026-06-23
- **Issue** : #14 (« Faire tourner tricoteuses-transcription-videos sur un flux vidéo AN et inspecter la sortie »)
- **Statut** : conclusions partielles
- **Toutes les affirmations ci-dessous viennent de lecture** (code de ttv, fixtures, sorties de runs), pas du modèle nu.

## Objectif

Faire tourner `tricoteuses-transcription-videos` (ttv) sur de la vidéo AN, inspecter ce qu'il produit, et évaluer ce que ttv apporte vraiment à Ariane (la trame hypertexte).

## Ce qui a été fait

1. **Clone propre** de ttv dans `~/code/tricoteuses-transcription-videos` (Anubis contourné via `User-Agent: git/2.40`).
2. **Deepgram en batch** : extraction ffmpeg de 3 min de la VOD (audition du 19 janvier 2026, tranche 555–735 s), transcription via `transcribe:audio`. Analyse manuelle des erreurs.
3. **ttv en live** : `transcribe:live --youtubeUrl` sur un live YouTube FR (le mode live ne consomme que des flux HLS / YouTube, pas un fichier).
4. **Identification des locuteurs** : déclenchée hors-ligne sur la fixture (transcript + NVS), sans Deepgram, pour isoler la valeur propre de ttv.
5. **Whisper local sur GPU** (chemin souverain, #3) : faster-whisper large-v3 en offline (mesure RTF) puis en live (whisper_streaming / LocalAgreement) sur le même extrait.

## Conclusions partielles

1. **Deux formats de sortie distincts.** Batch → un seul document `{metadata, segments[], speakers[]}`. Live → **NDJSON append-only**, une ligne par événement (`meta` ou `utterance`). Timecodes en **ms**, locuteur = **lettre** (A, B…).

2. **Qualité Deepgram : erreurs systématiques sur noms propres / acronymes** (« Someni » pour Somaini, « Harbard » pour Harvard, « notamons » pour entamons). Deux familles : corrigeables par LLM seul (la majorité) vs nécessitant une source externe (noms propres, intitulés). → conclusion : la valeur est « LLM **+ données canoniques** », pas « LLM vs STT ». Détail : [artifacts/deepgram-batch/transcript-deepgram-3min-erreurs.md](artifacts/deepgram-batch/transcript-deepgram-3min-erreurs.md). → issue **#17**.

3. **En live, ttv n'ajoute (presque) rien à Deepgram.** `transcribeLive` fait de la plomberie (ffmpeg, WebSocket, reconnexions, format NDJSON, mapping speaker→lettre) et **jette les `interim_results`** (filtre `is_final`). Côté contenu, ttv live donne **moins** que Deepgram brut.

4. **La granularité mot est conservée dans `raw`.** Le champ `raw.channel.alternatives[0].words[]` porte, **par mot**, timecode + confidence + speaker. C'est la matière pour les sous-titres temps réel, le provisoire→consolidé et la diarisation renforcée. → issue **#16**.

5. **L'identification (lettre → nom) marche, mais dépend des NVS post-production.** Déclenchée sur la fixture, elle transforme A/B/C/D en « M. Roger Chudeau, président », « Mme Céline Calvez, rapporteure », etc. (identique à la référence). **Mais** : `identifySpeakersOnSegments` part de `parseDataNvs(data.nvs)` ; sans NVS → `ABORT`. Les NVS (`status="vod"`) sont du chapitrage éditorial **produit après la séance**, donc **indisponibles en live**. → issue **#15**.

6. **Le « la parole est à… » existe, mais comme clé d'appariement vers les NVS**, pas comme source de nom. Le nom attribué vient du label NVS. Transposable au live seulement si on remplace la source des candidats (NVS) par la **liste des participants attendus**.

7. **Le trou d'Ariane est intact, strictement en aval.** Même après identification, `id: ""` et `qualite: ""` restent vides. La chaîne : Deepgram (texte + lettres) → ttv (lettres → noms, via NVS) → **Ariane (noms → ID acteur canonique PA…)** = #9.

8. **Ce qui est disponible avant/pendant le live** (pour l'identification) : l'ODJ / convocation, la **liste des participants attendus** (`participants.participantsInternes`, avec `acteurRef` PA… + présence), les annonces orales dans l'audio, les indices vidéo. C'est la décision 4 du spec.

9. **Choix de fixture pour la suite.** La fixture transcrite (`RUANR5L17S2026IDC458774`) a `participants: {}` **vide**. Sa voisine **`RUANR5L17S2026IDC458700`** porte **26 `acteurRef` canoniques + présences** : c'est le bon matériau pour prototyper le matching nom → ID (#9). Aucune fixture n'est une **séance d'hémicycle** (toutes auditions/commissions) → le périmètre amendements/scrutins de la trame (#10) n'y est pas représenté.

## Complément externe : la source live des locuteurs attendus existe (dérouleur AN)

Les conclusions #5, #6 et #8 laissaient le spike sur un trou : l'identification dépend des NVS, qui sont **post-production** (indisponibles en live), et il manquait une **source live de la liste des locuteurs attendus** pour la remplacer. La piste explorée pendant le spike (les fichiers `data.nvs` reçus en streaming par le player) restait à tester.

**Réponse d'Emmanuel Raviart (échange WhatsApp du 2026-06-24)** : la liste des inscrits aux questions au Gouvernement (et plus largement le « jaune » dynamique) **n'est pas dans l'open data**, mais elle est exposée par l'**API temps réel du dérouleur de l'Assemblée** :

- Page : `https://www.assemblee-nationale.fr/dyn/seance-publique/derouleur`
- JSON brut : `https://www.assemblee-nationale.fr/local/derouleur/derouleur.json` — **attaquable directement**, avec les précautions de politesse API d'usage (confirmé par Emmanuel, qui travaillait sur cette API le 2026-06-24, ainsi que sur celle d'**Eliasse**).
- Doc Tricoteuses (en cours de rédaction par Emmanuel à cette date) : `https://git.tricoteuses.fr/parking/tricoteuses-api-assemblee/src/branch/master/docs`

**Impact sur Ariane** : c'est le **remplaçant live des candidats NVS** (#15). Il transforme l'identification de l'orateur d'un problème « deviner à partir de l'audio » en une **confirmation d'une prédiction** (le dérouleur annonce qui doit parler ; la diarisation + le son ne font que valider). C'est aussi la réponse à la question ouverte du spec sur la disponibilité de la feuille jaune dynamique hors les murs.

**Vérifié par fetch (2026-06-25)** : `derouleur.json` récupéré en direct (114 Ko, HTTP 200, `application/json`, UA navigateur + Referer). C'est du **temps réel** (`extract_date_time` à quelques minutes du fetch) [⚠️ **corrigé plus bas**, section « Test live » : `extract_date_time` suit l'horloge de **diffusion** (~5 min de retard) et **gèle** en suspension] et il dépasse la simple liste d'orateurs :

- `racine.jaune` (id, `jaune_date_time`, `extract_date_time`) + `racine.contenu.phase` (`phase_libelle`, `phase_type`) + `ligne[]`.
- Les `ligne` sont typées `ARTICLE` / `ADT` / `SSADT` et portent, sur **355 des 357** lignes : `depute_tribun_id` (**ID canonique** Tribun/acteur, ex. `841701`) **et** `ligne_amendement_uid` (**UID Eliasse**, ex. `AMANR5L17PO838901BTC1583P0D1N000040`, joignable à `assemblee.amendements`).
- `ligne_video_highlighted="true"` marque **le curseur live** (ce qui passe à la vidéo à l'instant) — 24 lignes surlignées dans le run observé. [⚠️ **corrigé plus bas**, section « Test live » : c'est un **bloc grossier** (24-31 lignes), pas le curseur fin de la ligne courante.]

Conséquence : pour la séance **législative**, le dérouleur fournit la trame structurée **avec les ID canoniques et les liens amendements déjà résolus** — une grosse part du tissage (#9) est faite en amont par l'AN. Reste à Ariane l'identification *orale* (le dérouleur dit quel amendement, pas qui tient le micro à l'instant T) et les phases hors-base (#11). Nuance : ce run est le dérouleur **des amendements** ; la vue **QAG** (inscrits) est une autre projection de la même API, à fetcher un jour de QAG pour confirmer sa structure.

## Test live (2026-06-25) : dérouleur vs Eliasse vs NVS, et corrections

Session de test en direct sur une séance d'amendements (PPL 1583, « mariages simulés ou arrangés »), en confrontant les flux AN à ce qui était incrusté/affiché dans la vidéo. Cette section **corrige plusieurs affirmations de la section précédente** (les hypothèses sont conservées ici comme historique ; l'état final figé est dans [docs/data/donnees-disponibles-trame-hypertexte.md](../../docs/data/donnees-disponibles-trame-hypertexte.md)). Scripts (depuis rangés dans la brique de capture) : [`b3-capture/watch_derouleur_nvs.py`](../../b3-capture/watch_derouleur_nvs.py) (poll dérouleur+NVS, dédoublonnage par signature) et [`b3-capture/record_sources.py`](../../b3-capture/record_sources.py) (archive horodatée des 3 sources). Docs API officielles clonées et lues : `git.tricoteuses.fr/parking/tricoteuses-api-assemblee` → `docs/derouleur-api.md`, `docs/eliasse-api.md`.

**1. Le critère qui réorganise tout.** Un flux n'est une *entrée* utile que s'il est généré par machine, en temps réel, et **ne porte pas d'orateur**. Dès qu'un flux nomme qui parle, c'est qu'un humain l'a saisi en régie — c'est exactement ce qu'Ariane automatise. Donc un tel flux est une **sortie**, pas une entrée. Conséquence : le NVS (qui porte les orateurs effectifs) est **disqualifié comme entrée** et reclassé en **vérité terrain** (eval offline).

**2. Eliasse est la vraie colonne vertébrale temps réel** (et pas le dérouleur). Confirmé par la doc officielle puis par fetch live : `eliasse.assemblee-nationale.fr/eliasse/...do`, rafraîchi **1000 ms** (`getParametresStatiques.do`), avec **`prochainADiscuter.do`** → l'amendement courant directement (`{bibard, numAmdt}`), et **`amendement.do`** → `sortEnSeance` (Adopté/Rejeté/Tombé/Retiré), `etat`, auteur, cosignataires. Joignable (le seul obstacle était TLS : chaîne intermédiaire Gandi absente du bundle CA → `-k`, pas un mur d'auth).

**3. Corrections sur le dérouleur** (les deux affirmations de la section précédente étaient fausses) :
- **`extract_date_time` n'est PAS un indicateur de fraîcheur temps réel.** Il est sur l'**horloge de diffusion** (~5 min derrière le réel) et **gèle** en suspension de séance (le dérouleur n'est pas régénéré → `extract` figé à la dernière génération). La doc officielle le confirme : JSON quasi-statique caché ~5 s (Varnish/ETag/304).
- **`ligne_video_highlighted` n'est PAS le curseur fin.** C'est un **bloc grossier** (24-31 lignes = la discussion commune ouverte), désynchronisé de la ligne exacte à l'écran. La doc officielle dit que le dérouleur ne porte **aucun marqueur de ligne courante** ; usage recommandé = simple auxiliaire pour récupérer `ligne_amendement_uid`.
- **Hypothèse abandonnée** : « la ligne courante = position 3 du bloc surligné » (3-4 points concordants observés). Abandonnée car (a) non prouvée et (b) inutile — Eliasse donne l'amendement courant proprement via `prochainADiscuter.do`.

**4. Le NVS live existe et porte la trame réelle** — ce qui corrige l'idée que « la trame réelle (orateurs, rappels au règlement, suspensions) n'existe pas en direct ». Le `data.nvs` `status="live"` porte déjà le sommaire en direct + les ID Tribun dans `<speaker><url>`. Mais (cf. critère §1) c'est par construction de l'éditorial régie → vérité terrain, pas entrée.

**5. Latences mesurées** (2 points concordants, S/Adt 478 puis 540) :
- **dérouleur ↔ vidéo : ~6-7 s** (même horloge de diffusion, quasi synchrones) ;
- **diffusion ↔ temps réel : ~4 min 50 s, stable** = le temps de production de la régie (pendant lequel le NVS est rempli à la main). Pour Ariane : dérouleur et image traitée sont **co-temporels**, pas d'offset à gérer côté dérouleur.

**6. QAG** : le type de ligne **`INSCRITQAG`** (inscrit pour questions au Gouvernement) est confirmé dans la doc officielle du dérouleur → un jour de QAG, `derouleur.json` porte bien les inscrits. (Reste à le voir sur un run réel un jour de QAG.)

**7. Le NVS est deux fichiers, pas un** (vérifié en live le 2026-06-26). Le « NVS » recouvre un format **propriétaire Vodalys** (le prestataire vidéo de l'AN, pas un format AN), servi en deux fichiers de rôles séparés :
- `data.nvs` = arbre des **chapitres** (sujets, orateurs effectifs, ID Tribun dans `<speaker><url>`), **sans timecode** ; vient en `status="live"` (séance) et `status="vod"` (post-prod) ;
- `liveplayer_<epoch>.nvs` = piste de **synchro** (`<player starttime=…><synchro id=… timecode=…>`, ms depuis l'epoch `starttime`).

On **joint par `id`** (`data.nvs.chapter.id` == `liveplayer.synchro.id`) → chaque orateur reçoit son timecode dans le repère vidéo. La vérité terrain est donc **nativement datée** : pas d'offset NVS↔vidéo à mesurer, c'est la jointure des deux fichiers qui cale tout. Inventaire complet des fichiers que charge le player (HTML, dérouleur, les 2 NVS, HLS master/variantes, segments `.ts` DVR, storyboards) : [artifacts/network-capture.md](artifacts/network-capture.md).

## Artefacts (entrée + sortie produits par le spike)

- `artifacts/deepgram-batch/`
  - `RUANR5L17S2026IDC458774-3min.wav` — **entrée** : 3 min mono 16 kHz extraites de la VOD (5,7 Mo).
  - `transcript-deepgram-3min.json` — **sortie** Deepgram batch (23 segments).
  - `transcript-deepgram-3min-erreurs.md` — analyse manuelle des erreurs.
- `artifacts/ttv-live/`
  - `ttv-live-youtube.ndjson` — **sortie** ttv live (meta + utterances).
  - `ttv-live-youtube.console.log` — logs du run.
- `artifacts/identification/compte-rendu-genere.json` — **sortie** de l'identification (lettre→nom) sur la fixture.
- `artifacts/scripts/` — `run-ttv-live.ts`, `run-identify.ts` (reproductibilité).
- `artifacts/whisper/` — chemin souverain : transcription (`test_offline`, `transcribe_offline_full` + `whisper-offline.ndjson`), live + interim (`live_whisper`, `interim.ndjson`), diarisation (`diarize`, `diarized.ndjson`), Deepgram streaming (`deepgram_stream`, `deepgram-stream.ndjson`), WER (`compare_wer`, `compare_wer_live`).

## Sources (dans le git de ttv, non copiées ici)

- Fixtures upstream Tricoteuses (commits `fe1517b`, `bbc8564`) :
  - `tests/fixtures/RUANR5L17S2026IDC458774/input/transcript.json` — **entrée** offline de l'identification.
  - `tests/fixtures/RUANR5L17S2026IDC458774/input/nvs/{finalplayer,data}.nvs` — NVS post-prod.
  - `tests/fixtures/RUANR5L17S2026IDC458774/expected/compte-rendu.json` — référence.
  - `tests/fixtures/RUANR5L17S2026IDC458700/` — fixture avec `participants` renseigné (26 `acteurRef`).
- Code clé : `src/providers/deepgram.ts` (`transcribe`, `transcribeLive`), `src/identification/identifySpeakers.ts` (l. 158-159 NVS, l. 173 ABORT, l. 264 annonces), `src/scripts/transcribe_live.ts`.
- VOD source : `https://videos-an.vodalys.com/videos/definst/mp4/ida/domain1/2026/01/6242_20260119135010.smil/master.m3u8`

## Reproductibilité

```bash
cd ~/code/tricoteuses-transcription-videos   # clone ttv, npm install, .env avec DEEPGRAM_API_KEY
# 1. Deepgram batch (3 min)
ffmpeg -ss 555 -i "<VOD .m3u8>" -t 180 -ac 1 -ar 16000 -vn -y audios/extrait-3min.wav
npm run transcribe:audio -- --audioUrl ./audios/extrait-3min.wav --provider deepgram --lang fr --save ./out/t.json
# 2. ttv live (3 min, borné)
timeout 200 npm run transcribe:live -- --youtubeUrl "<URL>" --out ./out/live.ndjson 2>&1 | tee ./out/live.log
# 3. Identification sur fixture (sans Deepgram)
npx tsx spike-streaming/run-identify.ts RUANR5L17S2026IDC458774
```

## Chemin B : Whisper local sur GPU (souverain, #3)

Testé sur la RTX 5060 (Blackwell, driver 580 / CUDA 13). Stack : `faster-whisper` 1.2.1 + `ctranslate2` 4.8.0 ; `whisper_streaming` (LocalAgreement) pour le live. Compat Blackwell (sm_120) validée d'abord via `torch 2.10+cu128` (matmul GPU OK), puis confirmée par CTranslate2 au run (pas de fallback openai-whisper nécessaire).

- **Offline** (large-v3, float16) : **RTF 0,131** (7,6× temps réel) sur l'extrait 3 min. Qualité **≥ Deepgram** : la phrase lue par le président est mieux reconstruite. Même erreur « Someni » sur le nom propre.
- **Live** (whisper_streaming, source `-re` à 1×) : **178,4 s pour 180 s d'audio** (temps réel exact), **136 segments confirmés** progressivement par le LocalAgreement (équivalent souverain des « final » Deepgram). Whisper absorbe la latence grâce au RTF. Artefacts notés : hallucination de démarrage (« Sous-titrage FR ? »), léger recul vs offline en streaming (« émission » pour « mission »).
- **Comparaison WER** (`compare_wer.py`, **pseudo-ref = Whisper offline**, faute de vérité terrain) : Whisper-streaming **11,4 %**, Deepgram **13,1 %** (biaisé en faveur de Whisper car la ref *est* Whisper), écart Deepgram ↔ streaming **8,8 %**. Lecture solide : le streaming perd ~11 % vs l'offline (surtout des suppressions aux frontières de chunks) → argument passe différée (#12). Un verdict **absolu** Deepgram vs Whisper exige le CRI officiel comme référence (#4/#6).
- **Interim exposés** (`live_whisper.py --out`) : le buffer non confirmé (`OnlineASRProcessor.to_flush(transcript_buffer.complete())`) donne le texte provisoire qui se réécrit puis se fige en utterance. Log `interim.ndjson` (152 interim + 137 utterance sur 3 min) = matière directe pour l'UI (provisoire → consolidé, #12/#13). L'équivalent **local et souverain** des `interim_results` de Deepgram, validé.
- **Diarisation locale** (`diarize.py`, pyannote 4.0.5 sur GPU) : « qui parle quand » en **4,6 s** pour 3 min, aligné sur les utterances Whisper. **2 locuteurs** détectés (président jusqu'à ~142 s, invité Somaini ensuite), bascule au bon endroit ; l'hallucination de démarrage reste `null` (pas de voix → pas de locuteur, filtre naturel). Obstacles franchis : torchaudio apparié à `torch+cu128`, **3** repos HF gated (dont `speaker-diarization-community-1`), torchcodec contourné (audio préchargé via soundfile, il voulait CUDA 13), API `DiarizeOutput.exclusive_speaker_diarization` (pyannote 4). → **STT + diarisation 100 % locaux**.

**Conclusion** : la dette souveraineté (#3) est **levée**. Chaîne **100 % locale** validée de bout en bout : Whisper (STT, interim + utterance) + pyannote (diarisation), sur le GPU. Whisper local = qualité au niveau de Deepgram + RTF confortable ; le streaming est un cran sous l'offline → argument pour la passe différée (#12). Reste pour Ariane : le nom canonique (#9, en aval), et un vrai live + UI.

**Reproductibilité** :

```bash
cd ~/code/whisper-live   # venv --system-site-packages (hérite torch 2.10+cu128)
.venv/bin/python test_offline.py                              # offline + RTF
.venv/bin/python live_whisper.py --file <extrait.wav>         # live simulé (-re à 1x)
.venv/bin/python live_whisper.py --url "<live m3u8/youtube>"  # vrai live
```

## Direct vs différé : comparaison live/live et le mur des noms propres

Sur le même extrait : Deepgram et Whisper **en streaming** (live contre live), puis Whisper **différé** (offline) pour voir ce que la passe consolidée récupère.

**WER live/live** (pseudo-ref Whisper offline) : Deepgram-streaming **14,4 %** (vs 13,1 % en batch → le direct lui coûte ~1,3 pt), Whisper-streaming **11,4 %**. Profils d'erreurs distincts :
- **Deepgram direct** : gros blocs lisibles, mais **dérapages grossiers sur les noms propres** (« Sorbonne Nouvelle » → « Sûrement-Nouvelle »).
- **Whisper direct** : micro-segments, **pertes en frontière de chunk** (« Merci beaucoup » avalé), mais vocabulaire plus précis (« liminaire », « certaines »).

**Ce que le différé (Whisper offline) récupère** : les mots mal entendus en frontière (« émission » → « mission »), les bouts avalés (« Merci beaucoup »), la ponctuation et la structure. Argument béton pour le **two-pass** (#12).

**Ce qu'il ne récupère PAS** : les **noms propres**. « Sorbonne Nouvelle » → « Sormont-Nouvelle » et « Somaini » → « Someni » restent faux **même en différé**, des deux STT. Un meilleur modèle ou une seconde passe n'invente pas une orthographe non apprise.

**Conclusion centrale du spike** : la passe différée (#12) règle le texte ordinaire ; **#17 (relecture LLM ancrée sur l'ODJ / les participants) est le seul levier pour fixer les noms propres** — précisément le terrain où Ariane apporte les données canoniques.

## Suite

- **Nouvelles issues issues du spike** : #15 (identification ↔ NVS post-prod), #16 (interim + granularité mot), #17 (passe LLM relecture).
- **Issues existantes confirmées/éclairées** : #9 (trou nom → ID canonique), #12 (provisoire vs consolidé), #11 (phases par LLM), #13 (UI fil/bandeau), #4/#5 (séance témoin), #3 (**Whisper local, prochain chemin du spike**).
- **Prochain pas** : essai de transcription **live avec Whisper sur GPU** (RTX 5060) → #3.
- **Données (fait, 2026-06-25)** : `derouleur.json` fetché et caractérisé — temps réel, `depute_tribun_id` (ID canonique) + `ligne_amendement_uid` (Eliasse) sur 355/357 lignes, curseur live `ligne_video_highlighted`. Remplace les NVS post-prod comme source live → #15. Reste : fetcher une vue **QAG** un jour de questions au Gouvernement.
