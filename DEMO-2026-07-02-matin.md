# Démo Ariane — séance du 2 juillet 2026 (matin), 20 premières minutes

Pipeline **complet** sur la vraie séance : transcription CPU (faster-whisper) →
tissage du fil (weaver) → déduction orateurs / amendements / scrutins → fil
**horodaté** et **hyperlié** dans l'UI B4, avec seek vidéo au moment exact.

Bundle : `data/2026-07-02-matin` (vidéo 7,7 Go `hemi_20260702084503_1.mp4`,
dérouleur, référentiels, eliasse). Début de séance détecté à **t = 905488 ms**
(≈ 15 min 05 s dans la vidéo, soit 09:00:08). Sujet : *projet de loi sur la
justice criminelle et le respect des victimes*.

> Deux façons de démontrer :
> - **§2 — pipeline live** : la transcription tourne pour de vrai. Impressionnant,
>   mais **~0,46× le temps réel** sur ce CPU → 20 min de séance ≈ **~45 min de calcul**.
> - **§3 — replay instantané** (recommandé pour une démo devant public) : on fige
>   le STT réel **une fois ce soir**, puis demain le fil se rejoue **instantanément**
>   (0 GPU, 0 attente), à l'identique.
>
> Le plan idéal : **ce soir on lance §2 une fois** (ça valide tout + ça produit le
> STT), on le fige avec §3a, et **demain matin on démarre §3b** en 5 secondes.

---

## 1. Prérequis (déjà OK sur cette machine)

Vérification express :

```powershell
C:\Python314\python.exe -c "import faster_whisper, ctranslate2, numpy; print('py OK', faster_whisper.__version__)"
ffmpeg -version | Select-Object -First 1
```

- **Python à utiliser : `C:\Python314\python.exe`** (il a faster-whisper 1.2.1,
  ctranslate2, numpy). ⚠️ **Ne pas** utiliser `.venv\` : c'est un venv WSL,
  inutilisable côté Windows.
- `ffmpeg` doit être sur le PATH (v8.1.1 présente).
- Modèles déjà en cache Hugging Face : `mobiuslabsgmbh/faster-whisper-large-v3-turbo`
  (défaut, qualité) et `Systran/faster-whisper-small` (plus rapide).

Toutes les commandes se lancent depuis la racine du repo :
`C:\Users\timot\Projets\Hackathon_Assemblée\tricoteuses-ariane`.

---

## 2. Pipeline live complet (le run « toutes les étapes »)

Une seule commande orchestre B2 (replay) + B1 (STT + tissage) + B4 (UI) :

```powershell
C:\Python314\python.exe tools\run_option3_cpu.py --record data\2026-07-02-matin --duration-seconds 1200
```

- `--duration-seconds 1200` = les **20 premières minutes** de séance.
- Le départ est automatique au **début de séance** (`sitting_start_ms = 905488`) ;
  l'horodatage du fil est calé sur la vidéo (offset = 905488).
- Modèle par défaut : `large-v3-turbo` en `cpu/int8`.
  Alternative plus rapide, qualité moindre : ajouter `--model small`.
- Ports : **B2 `:8000`**, **B1 `:8100`** (SSE `/thread`), **B4 `:8080`**.

Le script affiche au démarrage le dossier de run
(`.runs\option3-cpu-XXXX\`) qui contient `b1.log`, `b2.log` et surtout
`thread.ndjson` (le fil produit). Il se termine tout seul une fois les 1200 s
traitées (`B1 completed normally`), ou avec `Ctrl+C`.

**Attendez la ligne `[3/5] B1 ready.`** (chargement du modèle, ~30–60 s) puis
`[5/5] Starting B2 clock and HLS...` avant d'ouvrir l'UI.

### Ouvrir l'UI et câbler la démo

Ouvrir **http://127.0.0.1:8080** puis :

1. **Fil Ariane B1 (SSE)** — le champ vaut déjà `http://127.0.0.1:8100/thread`.
   Si le fil ne démarre pas, cliquer le bouton **↻** à côté.
2. Cliquer **⏏ Source** (en bas à droite) pour rouvrir le sélecteur, puis
   **« VOD locale → Charger un MP4 »** → choisir
   **`data\2026-07-02-matin\video\demo-faststart.mp4`**.
   → C'est la source qui donne l'**horodatage exact** : `t` du fil = `currentTime`
   de la vidéo, alignés à la milliseconde, et **sans perturber** la transcription
   de B1 (qui, elle, lit le flux B2).

   ⚠️ **Ne pas cliquer « ▶ Direct »** : ça met l'UI en mode live et tente un flux
   Vodalys inexistant pour une séance passée (lecteur vide, badge « EN DIRECT »).

   ℹ️ Pourquoi `demo-faststart.mp4` et pas le gros MP4 ? Le fichier d'origine
   (`hemi_20260702084503_1.mp4`, 7,7 Go) n'est **pas faststart** (son index `moov`
   est à la fin) → le navigateur peut bloquer au chargement local. `demo-faststart.mp4`
   est une copie **faststart** des ~35 premières minutes (mêmes horodatages), qui se
   charge instantanément. Régénérable :
   `ffmpeg -y -ss 0 -to 2130 -i data\2026-07-02-matin\video\hemi_20260702084503_1.mp4 -c copy -movflags +faststart data\2026-07-02-matin\video\demo-faststart.mp4`

Ce que la démo montre alors, **en direct** :

- **Trame de gauche** : le fil se construit au fil de la parole — articles,
  appels d'amendement, orateurs, scrutins.
- **Clic sur un événement** → la **vidéo locale saute au moment exact**.
- **Liens fonctionnels** (fiches canoniques `assemblee-nationale.fr`) :
  - orateur → fiche du député (`/dyn/deputes/PA…`),
  - amendement → `/dyn/17/amendements/…`,
  - scrutin → `/dyn/17/scrutins/…`,
  - groupe → fiche de l'organe.
- Bouton **🔍 Glass-box** : sous chaque événement, la phrase entendue (source) et
  la confiance — pour montrer que le fil est **déduit de la parole**, pas recopié.

> Vérifié sur les 150 premières secondes : orateur *M. Emmanuel Duplessy*
> (→ PA841351), amendements n° 245 / 30 / 16 / 10 / 20 (UID canoniques résolus),
> un *Scrutin ouvert*. Les liens se remplissent donc bien.

### Ce qui est normal au démarrage

- `[stream] source ended → reconnecting` pendant ~4–6 s : préchauffage ffmpeg du HLS.
- `[referentials] fetch failed ('racine')` puis `[referentials] back up` : à 09:00:03
  le snapshot dérouleur capté est momentanément vide (`{}`) ; B1 le repolle et se
  répare en < 30 s. Les toutes premières phrases peuvent manquer de contexte d'article.

### Rythme

À ~0,46× le temps réel, le fil se remplit **environ 2× plus lentement** que la
séance : les 20 min sont traitées en ~45 min. Pour une démo live fluide, préférez
le **replay instantané (§3)** ; gardez le pipeline live pour *montrer que la
transcription tourne vraiment* (ex. sur les 3–5 premières minutes pendant que vous
commentez).

---

## 3. Replay instantané pour demain matin (recommandé pour le public)

L'idée : la transcription CPU est lente, donc on la fait **une seule fois ce soir**
et on **fige le STT réel** dans le bundle. Demain, `b4-ui/demo_replay.py` re-tisse
le **même** fil (mêmes cœurs purs, mêmes référentiels) **instantanément**, sert la
vidéo, et l'UI est identique — mais sans aucune attente.

### 3a. Ce soir — figer le STT (après que le run §2 soit terminé)

```powershell
# récupère automatiquement le dernier dossier de run produit par §2
$run = Get-ChildItem .runs -Directory -Filter 'option3-cpu-*' | Sort-Object LastWriteTime | Select-Object -Last 1
C:\Python314\python.exe tools\thread_to_stt_offline.py "$($run.FullName)\thread.ndjson" data\2026-07-02-matin\stt-offline-large-v3.ndjson
```

Cela écrit `data\2026-07-02-matin\stt-offline-large-v3.ndjson` (segments
`{beg, end, text}`). **C'est le seul artefact à conserver pour demain.**

### 3b. Demain matin — la démo en 2 commandes

Dans **deux** terminaux (ou l'un en arrière-plan) :

```powershell
# terminal 1 : re-tisse le fil hors-ligne + le sert en SSE sur :8100 (même forme que B1)
#   --ocr = scanne demo-faststart.mp4 (tesseract) et tisse le chiffré des scrutins
#           (votants/exprimés/majorité/POUR/CONTRE). ~quelques min de scan, UNE fois.
C:\Python314\python.exe b4-ui\demo_replay.py --bundle data\2026-07-02-matin --port 8100 --ocr

# terminal 2 : sert l'UI
C:\Python314\python.exe b4-ui\serve.py --port 8080
```

> Le scan OCR écrit le fil complet dans `b4-ui\thread.ndjson`. Pour **redémarrer
> instantanément** ensuite (sans re-scanner), servir ce fichier tel quel :
> `demo_replay.py --bundle data\2026-07-02-matin --port 8100 --thread-file b4-ui\thread.ndjson`.
> Sans `--ocr`, la démo montre déjà le badge et les demandeurs (déduits de la parole) ;
> seuls les **chiffres du scrutin** (lus sur l'écran-résultat) nécessitent le scan.

Puis **http://127.0.0.1:8080** :

1. **Fil Ariane B1 (SSE)** = `http://127.0.0.1:8100/thread` (déjà par défaut) → **↻**.
   Tout le fil arrive d'un coup (l'UI dédoublonne par `seq`).
2. **⏏ Source → VOD locale → Charger un MP4** → le même clip
   **`data\2026-07-02-matin\video\demo-faststart.mp4`** (pas « ▶ Direct »).

Le fil complet des 20 min s'affiche **instantanément**, cliquable, horodaté, avec
tous les liens — sans GPU, sans réseau, sans attente.

**Scrutins publics** (nouveau) : quand le président annonce « je suis saisie de
scrutin public », les amendements concernés portent un **badge « scrutin public »** ;
si les **groupes demandeurs** sont nommés (« demandé respectivement par les groupes
La France insoumise et LIOT »), la carte affiche **« Scrutin demandé par … »** (lien
vers la fiche du groupe). À la proclamation, l'**écran-résultat** incrusté est lu par
OCR et la carte se complète des **chiffres** (POUR / CONTRE / votants / majorité).
Exemple à ~18 min : amendement n° 310 (M. Molac), demandé par LIOT.

---

## 4. Dépannage

- **Port déjà utilisé** : un run précédent traîne. Fermer le terminal, ou changer
  les ports (`--b2-port / --b1-port / --b4-port` pour §2).
  Repérer/tuer un serveur : `Get-NetTCPConnection -LocalPort 8100 | Select OwningProcess`
  puis `Stop-Process -Id <pid>`.
- **`B1 exited with code …`** : lire la fin de `\.runs\option3-cpu-XXXX\b1.log`.
- **Erreur de modèle / téléchargement** : ajouter `--allow-model-download` à la
  commande §2 (le cache par défaut est déjà complet, donc normalement inutile).
- **Pas de vidéo / lecteur vide « EN DIRECT »** : tu as cliqué « ▶ Direct ». Cliquer
  **⏏ Source** puis **VOD locale → Charger un MP4** = `demo-faststart.mp4`. Ne jamais
  utiliser « ▶ Direct » (flux live) ni « Replay B2 » (B2 n'est pas lancé en mode replay).
- **Le gros MP4 (7,7 Go) bloque au chargement** : normal, il n'est pas faststart.
  Utiliser `demo-faststart.mp4` (voir §2 pour le régénérer).
- **Rappel** : toujours `C:\Python314\python.exe`, jamais `.venv\`.

---

## Aide-mémoire (copier-coller)

```powershell
# --- CE SOIR : run complet (les vraies 20 min, ~45 min de calcul) ---
C:\Python314\python.exe tools\run_option3_cpu.py --record data\2026-07-02-matin --duration-seconds 1200
#   UI : http://127.0.0.1:8080  → SSE :8100/thread (↻)  + ⏏ Source → VOD locale = demo-faststart.mp4  (PAS ▶ Direct)

# --- CE SOIR (une fois le run fini) : figer le STT pour demain ---
$run = Get-ChildItem .runs -Directory -Filter 'option3-cpu-*' | Sort-Object LastWriteTime | Select-Object -Last 1
C:\Python314\python.exe tools\thread_to_stt_offline.py "$($run.FullName)\thread.ndjson" data\2026-07-02-matin\stt-offline-large-v3.ndjson

# --- DEMAIN MATIN : replay instantané ---
C:\Python314\python.exe b4-ui\demo_replay.py --bundle data\2026-07-02-matin --port 8100 --ocr     # terminal 1 (--ocr : chiffré des scrutins ; ~qq min de scan une fois)
C:\Python314\python.exe b4-ui\serve.py --port 8080                                                # terminal 2
#   redémarrage instantané sans re-scan : ... --port 8100 --thread-file b4-ui\thread.ndjson
#   UI : http://127.0.0.1:8080  → SSE :8100/thread (↻)  + ⏏ Source → VOD locale = demo-faststart.mp4  (PAS ▶ Direct)
```
