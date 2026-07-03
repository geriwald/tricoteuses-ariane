# Erreurs de transcription Deepgram — relevé manuel

Expérience : passer au crible la sortie brute de Deepgram pour qualifier ce qu'une
passe LLM de relecture (spec Ariane, décision 2) devrait rattraper.

## Cadre

- **Audio** : `audios/RUANR5L17S2026IDC458774-3min.wav`, tranche 555 s → 735 s de la
  VOD `videos-an.vodalys.com/.../6242_20260119135010.smil/master.m3u8`.
- **Source analysée** : `out/transcript-deepgram-3min.json`, champ
  `metadata.raw.results.channels[0].alternatives[0].transcript` (3202 caractères).
- **Réunion** : audition (commission, mission « IA, création, culture, éducation »),
  19 janvier 2026. Locuteurs : président **Roger Chudeau** (A, jusqu'à 134 s),
  invité **Antonio Somaini** (B, à partir de 144 s), rapporteure citée **Céline Calvez**.
- **Provider** : Deepgram `nova-3`, langue `fr`, diarisation activée.

## Avertissement de méthode

Je n'ai pas réécouté l'audio. Les corrections viennent du **contexte connu**
(noms propres de l'audition, cohérence grammaticale) et du **raisonnement**, pas
d'une vérité de référence : la fixture `expected/compte-rendu.json` porte les
**mêmes** erreurs (« Someni », « DIT »), elle n'est pas post-éditée. Niveau de
certitude noté par erreur : 🟢 quasi certain · 🟡 probable · 🔴 hypothèse à vérifier à l'audio.

---

## 1. Noms propres et termes spécialisés

| Transcrit | Correction | Cert. | Note |
|---|---|---|---|
| « monsieur Antonio **Someni** » (×2) | Antonio **Somaini** | 🟢 | Nom de l'auditionné, attesté par l'ordre du jour de la réunion. |
| « à **Harbard** en 2024 et 25 » | **Harvard** | 🟢 | Cité juste après Yale : « 2 universités américaines à Yale… et à Harvard ». |
| « professeur en **DUT** dans 2 universités américaines » | « professeur **invité** » (visiting professor) ? | 🔴 | « DUT » n'a aucun sens ici ; la fixture dit « DIT », tout aussi faux. Terme à confirmer à l'audio. |

## 2. Mots et formes erronés (homophones, non-mots)

| Transcrit | Correction | Cert. | Note |
|---|---|---|---|
| « Nous **notamons** cet après-midi une 2e phase » | « Nous **entamons** » | 🟢 | « notamons » n'existe pas ; « entamer une phase » est la collocation attendue. |
| « **puisqu'on avez** bien expliqué » | « **puisqu'on nous a** bien expliqué » | 🟢 | « on avez » est grammaticalement impossible ; homophonie écrasée. |

## 3. Accords et grammaire

| Transcrit | Correction | Cert. | Note |
|---|---|---|---|
| « touche déjà à **certains** des questions » | « **certaines** des questions » | 🟢 | Accord féminin. |
| « les questions qu'elle a **préparé** » | « **préparées** » | 🟢 | Accord du participe avec le COD antéposé. |
| « associer autant que possible **les** universitaires » | « **des** universitaires » | 🟡 | Sens : associer des universitaires en général à la mission. |

## 4. Répétitions et reprises orales (le président lit et se reprend)

| Transcrit | Lecture probable | Cert. | Note |
|---|---|---|---|
| « **Vous nous pourrez** également **nous** dire un mot » | « Vous pourrez également nous dire un mot » | 🟢 | Double « nous » : amorce abandonnée puis reprise. |
| « …de la mission d'information. **Je répète à chaque fois, désolé,** à la création, la diffusion… » | incise orale insérée dans la lecture de l'intitulé | 🟢 | Pas une faute lexicale : le président s'écarte du texte lu, ce qui hache la phrase. |

## 5. Ponctuation et segmentation des phrases

| Transcrit | Correction | Cert. | Note |
|---|---|---|---|
| « …notre éducation et notre culture **Tel est** le thème… » | « …notre culture**.** Tel est le thème… » | 🟢 | Point manquant : deux phrases fusionnées (fin de l'intitulé lu, puis reprise). |
| « mission d'information. […] à la création, la diffusion et à l'acquisition des connaissances. Comment l'IA transforme notre éducation et notre culture. » | « mission d'information **sur** la création, la diffusion et l'acquisition des connaissances **:** comment l'IA transforme notre éducation et notre culture » | 🟡 | Reconstruction de l'intitulé officiel lu par le président. La ponctuation Deepgram découpe le titre en fragments. |

## 6. Diarisation

| Observé | Problème | Cert. | Note |
|---|---|---|---|
| 179 s : fragment « **suis** » attribué au locuteur **A** | Or c'est Somaini (B) : « Je suis professeur… » | 🟢 | Erreur d'attribution sur un fragment court en fin de fenêtre. |
| Champ `transcript` brut : « …à votre attention. Merci beaucoup pour cette introduction… » | Bascule Chudeau → Somaini **invisible** | n/a | Limite structurelle, pas une faute : la séparation n'existe que dans `segments`/`utterances`. |

---

## Ce que l'expérience dit pour Ariane

- **Corrigeable par un LLM sans source externe** (connaissance générale + cohérence) :
  Harvard, « entamons », « on nous a », tous les accords, le double « nous », la
  ponctuation, la segmentation. C'est la majorité des erreurs, et ça valide la
  thèse : un LLM rattrape le gros de ce que Deepgram rate.
- **Nécessite une source externe** (un LLM nu ne suffit pas, ou hallucine) :
  l'orthographe des noms propres (« Somaini »), l'intitulé exact de la mission, le
  terme « professeur invité ». C'est précisément là que **la trame hypertexte
  d'Ariane apporte le contexte canonique** (ordre du jour, liste des participants,
  dossier de la mission) qui sécurise la correction au lieu de la deviner.

Conclusion : la valeur n'est pas « LLM vs Deepgram » mais « LLM **+ données
canoniques** ». L'audition le montre en petit ; une séance d'hémicycle (amendements,
scrutins) le montrerait en grand.
