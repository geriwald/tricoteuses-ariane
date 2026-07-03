# Éval : passe LLM de relecture (proofread) sur transcript réel

- **Date** : 2026-07-03
- **Chantier** : passe LLM de relecture (#17), spec [2026-07-03-b1-llm-proofread-pass-design.md](../../docs/specs/2026-07-03-b1-llm-proofread-pass-design.md), implémentée dans [`b1-weaver/proofread.py`](../../b1-weaver/proofread.py)
- **Statut** : concluant — option D (Sonnet + indices difflib) validée et actée dans la spec
- **Toutes les affirmations ci-dessous viennent de lecture** (runs réels exécutés sur caladan, sorties archivées dans [`artifacts/`](artifacts/)), pas du modèle nu.

## Objectif

Valider sur données réelles que la passe de relecture corrige les noms propres
et coquilles STT en s'appuyant sur la liste résolue de la séance, sans jamais
inventer — et trancher le choix du modèle (Haiku suffit-il ?).

## Protocole

- **Entrée** : `stt-offline-large-v3.ndjson` de la capture `2026-06-26-evening`
  (séance FIN DE VIE, faster-whisper large-v3 offline, 423 segments), converti
  en nœuds `utterance/consolidated`.
- **Candidats** : `referential/acteurs.json` du bundle (136 acteurs résolus).
- **Transport** : `claude -p --model <m>` local (abonnement), fenêtres de 20
  utterances, chevauchement 2.

```bash
cd b1-weaver
python proofread.py --thread thread-2026-06-26.ndjson \
    --actors /mnt/data/ariane-capture/2026-06-26-evening/referential/acteurs.json \
    --limit 100
```

## Conclusions

1. **Haiku ne suffit pas pour les noms propres.** Il corrige les coquilles
   (« au voie » → « aux voix », 3/3) mais rate deux fois le match flou
   « madame Bruet » → Gruet contre la liste des 136 candidats — flaggé « ne
   correspond à aucun candidat » alors que Mme Justine Gruet y figure
   ([artifacts/run1-haiku.ndjson](artifacts/run1-haiku.ndjson), deux runs dont
   un avec prompt renforcé). Chercher une aiguille floue dans 136 lignes est
   au-dessus de son attention. Latence : ~1 min 20 pour 2 fenêtres.

2. **Sonnet réussit tout, latence équivalente** (~1 min pour 2 fenêtres, le
   démarrage du CLI domine). Sans indices, il retrouve même la formule de
   scrutin cohérente avec l'arithmétique du vote (pour 25 + contre 40 = 65
   exprimés, là où la ponctuation STT donnait 58 ≠ 65)
   ([artifacts/run3-sonnet-sans-indices.ndjson](artifacts/run3-sonnet-sans-indices.ndjson)).

3. **Option D retenue : Sonnet par défaut + indices difflib injectés.** Les
   noms détectés (`deduce.extract_speaker_names`) sont pré-résolus par
   `resolve_id.resolve` (difflib, résout « Bruet » → Gruet à 0.80 depuis le
   début) et injectés dans le prompt. Le travail flou est fait par du code
   déterministe et testé ; le LLM confirme en contexte. Avec indices : zéro
   flag parasite, correction directe.

4. **Test principal : 10 corrections sur 100 utterances, toutes légitimes,
   zéro invention** ([artifacts/proofread-test100.ndjson](artifacts/proofread-test100.ndjson),
   5 fenêtres Sonnet, ~4 min) :

   | seq | Avant | Après |
   |---|---|---|
   | 13 | je mets **au voie** le 1388 | je mets **aux voix** le 1388 |
   | 17 | **Votant** 62 exprimés | **Votants** 62 exprimés |
   | 20 | madame **Bruet**, défendu | madame **Gruet**, défendu |
   | 28 | mettre **au voie** | mettre **aux voix** |
   | 29 | mettre **au voie** cet amendement 449 | mettre **aux voix** cet amendement 449 |
   | 33 | 65 **majorités**, 33 pour | 65 **majorité**, 33 pour |
   | 44 | Nathalie **Collin-Osteller-Lay** | Nathalie **Colin-Oesterlé** |
   | 46 | délai obligatoire de **réfection** | délai obligatoire de **réflexion** |
   | 81 | mettre **en voie** cet amendement | mettre **aux voix** cet amendement |
   | 89 | Madame **Louboucher** | Madame **Leboucher** |

   Les chiffres (numéros d'amendement, décomptes) sont intacts partout.
   Lecture en continu avec corrections mises en évidence (barré/gras) :
   [transcript-corrige.md](transcript-corrige.md).

5. **Les trois noms corrigés viennent bien des candidats** (vérifié dans
   `acteurs.json`) : Mme Justine Gruet (PA794058), Mme Nathalie Colin-Oesterlé
   (PA841431), Mme Élise Leboucher (PA795108). Le cas 44 est notable : sans
   civilité devant le nom, il n'avait **pas** d'indice difflib (la détection
   ne couvre que « M./Mme + Nom ») — Sonnet a matché directement contre la
   liste. Les indices sont un filet, pas une béquille obligatoire.

6. **Les 3 flags émis sont pertinents et sobres**
   ([artifacts/proofread-test100.log](artifacts/proofread-test100.log)) :
   formule de scrutin suspecte (seq 17), correction phonétique à valider
   contre l'audio (seq 46 — flag *en plus* de la correction), disfluence
   laissée telle quelle (seq 95). Le comportement D2 « ne jamais inventer »
   tient : « Someni » (nom hors candidats, runs 1-3) a toujours été flaggé,
   jamais réécrit.

## Limites connues

- Un mot coupé **à cheval sur deux utterances** (frontière de chunk STT) n'est
  pas réparable : le contrat par-seq interdit la fusion (spec D3bis). C'est le
  travail de la 2e passe Whisper sur chunks recollés, en amont (chantier à
  venir).
- Les indices difflib ne couvrent que les noms précédés d'une civilité ;
  extensible si l'éval sur d'autres séances montre des ratés sur les noms nus.
- Éval mono-séance (FIN DE VIE, 26/06) ; à rejouer sur une séance de QAG
  (vocabulaire et rythme différents).

## Coût / latence

~1 appel CLI Sonnet par fenêtre de 20 utterances (~45-60 s, démarrage CLI
inclus), sur l'abonnement — soit ~21 appels pour la séance complète de 423
utterances. Compatible avec un post-traitement de séance ; pour le live, le
débit de parole (~1 fenêtre/2-3 min) laisse une marge confortable.

## Prompt de correction évalué

Version figée telle qu'évaluée par le run principal (la version vivante est
[`b1-weaver/prompts/proofread.md`](../../b1-weaver/prompts/proofread.md)).
Les jetons `<<CANDIDATES>>`, `<<HINTS>>`, `<<CONTEXT>>` et `<<TARGETS>>` sont
remplacés à chaque appel par `build_prompt` : candidats de la séance rendus en
`Civ Prénom Nom`, indices difflib, puis les utterances en liste `[seq] texte`.

````markdown
Tu relis la transcription automatique (STT) d'une séance publique de
l'Assemblée nationale. Ta seule mission : corriger, dans le texte, les noms
propres estropiés par le STT, les acronymes parlementaires mal transcrits et
les coquilles manifestes de reconnaissance vocale (« je mets au voie » → « je
mets aux voix »). Tu ne reformules pas, tu ne résumes pas, tu ne changes ni le
style ni la ponctuation au-delà de la correction.

## Règles absolues

1. **Interdiction d'inventer.** Tu ne corriges un nom propre que s'il
   correspond, à une déformation phonétique près, à un candidat de la liste
   ci-dessous. Si aucun candidat ne matche avec confiance, tu laisses le texte
   TEL QUEL et tu poses un flag. Une correction inventée est pire qu'une
   erreur STT visible.
   **Symétriquement** : le STT déforme systématiquement les noms qu'il ne
   connaît pas. Un nom entendu qui ressemble fortement à UN SEUL candidat
   (une lettre ou un son près : « madame Berrin » alors que seule
   « Mme Claire Perrin » est candidate) DOIT être corrigé vers ce candidat —
   c'est exactement le travail attendu. Ne flagge que si plusieurs candidats
   sont plausibles ou si la ressemblance est lointaine.
2. **Une utterance = une correction.** Tu ne fusionnes jamais deux utterances,
   tu n'en scindes jamais une. Chaque correction reprend le texte INTÉGRAL de
   l'utterance, corrigé.
3. **Le contexte est en lecture seule.** Les utterances de la section
   « Contexte » servent uniquement à comprendre le fil ; toute correction les
   visant sera rejetée.
4. Les nombres (numéros d'amendement, d'article) sont fiables : n'y touche pas.

## Acronymes et vocabulaire parlementaire courants

PPL (proposition de loi), PJL (projet de loi), CMP (commission mixte
paritaire), QAG (questions au Gouvernement), CRA (compte rendu analytique),
ADT (amendement), sous-amendement, scrutin public, rappel au règlement,
motion de rejet préalable, article 40, article 45, article 49 alinéa 3.

## Orateurs et personnalités de la séance (noms canoniques, source de vérité)

<<CANDIDATES>>

<<HINTS>>

Ces indices sont calculés par comparaison déterministe (difflib) entre les
noms entendus et la liste des candidats. Confirme ou rejette chaque indice en
contexte : une suggestion cohérente avec le fil DOIT être appliquée ; un
indice « aucun candidat proche » signifie laisser tel quel et flagger.

<<CONTEXT>>

<<TARGETS>>

## Format de réponse

Réponds UNIQUEMENT avec un objet JSON, sans texte autour, sans balises de
code :

{"corrections": [{"seq": <int>, "text": "<texte intégral corrigé>", "changes": ["<avant>→<après>", ...], "flags": ["<doute ou nom inconnu>", ...]}]}

- N'inclus que les utterances modifiées ou flaggées ; si rien à signaler :
  {"corrections": []}
- `seq` reprend exactement le numéro entre crochets de l'utterance visée.
- `changes` liste chaque substitution effectuée.
- `flags` signale, en français, un nom absent des candidats ou un doute
  (texte alors inchangé).
````
