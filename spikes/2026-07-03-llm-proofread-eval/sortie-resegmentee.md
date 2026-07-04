# Sortie de la passe de relecture LLM — séance FIN DE VIE (26/06)

> Démo B1 · brique #17 · généré le 2026-07-03 sur caladan · modèle : Claude Sonnet via CLI local

## Ce que fait cette passe

La transcription automatique (STT) découpe la parole en fragments souvent
coupés en plein milieu d'une phrase, avec des noms propres estropiés. Le
dernier étage de B1 relit ce texte, le **corrige** (noms propres résolus
contre la liste des orateurs de la séance, acronymes, coquilles) et le
**recompose** en prises de parole lisibles. Un nœud corrigé peut donc en
**remplacer plusieurs** (fusion de fragments) — c'est le champ `supersedes`,
qui devient une liste de `seq`.

Extrait ci-dessous : les **100 premières utterances** (ouverture + premiers
scrutins), soit 24 nœuds produits dont 18 fusions. Format : les fragments
**STT bruts** (avec leur `seq` et l'horodatage vidéo) → la **prise de parole
corrigée**.

---

### `14:10` — correction

STT brut :

> `[1]` Et donc cet après-midi, alors l'ordre du jour rappelle la suite de la discussion en nouvelle lecture de la proposition de loi relative aux droits à l'aide à mourir.

Corrigé :

> **Et donc cet après-midi, l'ordre du jour rappelle la suite de la discussion en nouvelle lecture de la proposition de loi relative aux droits à l'aide à mourir.**

### `14:18` — correction

STT brut :

> `[2]` Cet après-midi, l'Assemblée a poursuivi l'examen des articles s'arrêtant à l'amendement numéro 1242 à l'article 6.

Corrigé :

> **Cet après-midi, l'Assemblée a poursuivi l'examen des articles, s'arrêtant à l'amendement numéro 1242 à l'article 6.**

### `14:32` — correction

STT brut :

> `[4]` Il y a eu un certain nombre de retraits et je vous indique que sur les amendements 1242 et 1388, il y a des scrutins publics qui sont demandés et que je fais annoncer dans l'ensemble de l'Assemblée nationale.

Corrigé :

> **Il y a eu un certain nombre de retraits, et je vous indique que sur les amendements 1242 et 1388, il y a des scrutins publics qui sont demandés et que je fais annoncer dans l'ensemble de l'Assemblée nationale.**

### `14:44` — fusion de 2 fragments

STT brut :

> `[5]` Alors le premier n'est pas défendu, le 1429 n'est pas défendu, 1388 défendu.
> `[6]` Et le 1229.

Corrigé :

> **Alors le premier n'est pas défendu, le 1429 n'est pas défendu, 1388 défendu. Et le 1229.**

### `15:11` — correction

STT brut :

> `[8]` Alors madame ou monsieur le rapporteur sur l'amendement 1388.

Corrigé :

> **Alors, madame ou monsieur le rapporteur, sur l'amendement 1388 ?**

### `15:17` — correction

STT brut :

> `[10]` Et madame la ministre.

Corrigé :

> **Et madame la ministre ?**

### `15:22` — fusion de 3 fragments

STT brut :

> `[13]` Donc je mets au voie le 1388 qui fait l'objet d'un scrutin public.
> `[14]` Le scrutin, donc double avis défavorable, commission, gouvernement.
> `[15]` Le scrutin est ouvert.

Corrigé :

> **Donc je mets aux voix le 1388, qui fait l'objet d'un scrutin public — double avis défavorable, commission, gouvernement. Le scrutin est ouvert.**

### `15:46` — fusion de 2 fragments

STT brut :

> `[17]` Votant 62 exprimés, 62 majorités.
> `[18]` 32 pour, 23 contre, 39, l'Assemblée nationale n'a pas adopté.

Corrigé :

> **Votant 62, exprimés 62, majorité 32 ; pour 23, contre 39 ; l'Assemblée nationale n'a pas adopté.**

### `16:02` — fusion de 3 fragments

STT brut :

> `[20]` L'amendement 449, madame Bruet, défendu pour la commission.
> `[21]` Défavorable.
> `[22]` Défavorable.

Corrigé :

> **L'amendement 449, madame Gruet. Défendu. Pour la commission : défavorable. Défavorable.**

### `16:11` — fusion de 2 fragments

STT brut :

> `[23]` Je vous indique que sur cet amendement, je suis saisie d'une demande au scrutin public
> `[24]` que je fais annoncer dans l'ensemble de l'Assemblée nationale.

Corrigé :

> **Je vous indique que sur cet amendement, je suis saisie d'une demande au scrutin public que je fais annoncer dans l'ensemble de l'Assemblée nationale.**

### `16:17` — fusion de 3 fragments

STT brut :

> `[25]` Madame la ministre.
> `[26]` Défavorable.
> `[27]` Défavorable.

Corrigé :

> **Madame la ministre. Défavorable. Défavorable.**

### `16:22` — fusion de 3 fragments

STT brut :

> `[28]` Je vais mettre au voie.
> `[29]` Je vais mettre au voie cet amendement 449 qui vient de recevoir un double avis défavorable,
> `[30]` commission, gouvernement.

Corrigé :

> **Je vais mettre aux voix cet amendement 449 qui vient de recevoir un double avis défavorable, commission, gouvernement.**

### `16:39` — fusion de 2 fragments

STT brut :

> `[33]` Votant 65 exprimés, 65 majorités, 33 pour, 25 contre, 40.
> `[34]` L'Assemblée nationale n'a pas adopté.

Corrigé :

> **Votants 65, exprimés 65, majorité 33, pour 25, contre 40. L'Assemblée nationale n'a pas adopté.**

### `16:46` — fusion de 4 fragments

STT brut :

> `[35]` Nous avons ensuite des identiques.
> `[36]` Alors, le 734 qui fait l'objet d'une demande au scrutin public
> `[37]` que j'annonce dans l'ensemble de l'Assemblée nationale.
> `[38]` Le 1357 et le 1360 également.

Corrigé :

> **Nous avons ensuite des identiques. Alors, le 734, qui fait l'objet d'une demande au scrutin public que j'annonce dans l'ensemble de l'Assemblée nationale, le 1357 et le 1360 également.**

### `17:01` — fusion de 12 fragments

STT brut :

> `[40]` Monsieur Bazin.
> `[41]` Oui, merci Madame la Présidente.
> `[42]` Madame la Ministre, Monsieur le Président de la Commission, Monsieur le Rapporteur général,
> `[43]` Madame la rapporteure, mes chers collègues.
> `[44]` Je défends cet amendement de Nathalie Collin-Osteller-Lay du groupe Horizon
> `[45]` parce que je le trouve très intéressant.
> `[46]` Elle prévoit que le délai obligatoire de réfection ne peut être inférieur à 15 jours
> `[47]` pour les personnes sous mesure de protection.
> `[48]` Et on le voit bien, le temps que la personne chargée de la mesure de protection
> `[49]` puisse en prendre connaissance, puisse potentiellement faire un recours.
> `[50]` Je pense que c'est nécessaire de prévoir un délai au moins de 15 jours,
> `[51]` au moins pour les personnes qui sont sous mesure de protection.

Corrigé :

> **M. Thibault Bazin. Oui, merci Madame la Présidente. Madame la Ministre, Monsieur le Président de la Commission, Monsieur le Rapporteur général, Madame la rapporteure, mes chers collègues. Je défends cet amendement de Mme Nathalie Colin-Oesterlé du groupe Horizons parce que je le trouve très intéressant. Elle prévoit que le délai obligatoire de réfection ne peut être inférieur à 15 jours pour les personnes sous mesure de protection. Et on le voit bien, le temps que la personne chargée de la mesure de protection puisse en prendre connaissance, puisse potentiellement faire un recours. Je pense que c'est nécessaire de prévoir un délai au moins de 15 jours, au moins pour les personnes qui sont sous mesure de protection.**

### `17:40` — correction

STT brut :

> `[52]` Je vous remercie Monsieur Bazin.

Corrigé :

> **Je vous remercie, Monsieur Bazin.**

### `17:43` — fusion de 2 fragments

STT brut :

> `[53]` L'amendement 816, Madame...
> `[54]` Alors, je crois qu'il n'est pas défendu.

Corrigé :

> **L'amendement 816, Madame... Alors, je crois qu'il n'est pas défendu.**

### `18:03` — fusion de 8 fragments

STT brut :

> `[63]` Merci Madame la Présidente.
> `[64]` Vous savez que, Monsieur Bazin, que le texte comprend des mesures spécifiques
> `[65]` pour les majeurs protégés que nous avons renforcées en première,
> `[66]` comme en deuxième lecture.
> `[67]` Donc, je pense notamment à l'information de la personne chargée de la mesure de protection,
> `[68]` à l'avis d'un médecin spécialiste des majeurs protégés
> `[69]` et à l'ouverture d'une voie de recours aux personnes chargées des mesures de protection.
> `[70]` Donc, pour toutes ces raisons, défavorable.

Corrigé :

> **Merci Madame la Présidente. Vous savez que, M. Thibault Bazin, le texte comprend des mesures spécifiques pour les majeurs protégés que nous avons renforcées en première, comme en deuxième lecture. Je pense notamment à l'information de la personne chargée de la mesure de protection, à l'avis d'un médecin spécialiste des majeurs protégés et à l'ouverture d'une voie de recours aux personnes chargées des mesures de protection. Donc, pour toutes ces raisons, défavorable.**

### `18:31` — fusion de 8 fragments

STT brut :

> `[72]` Oui, merci Madame la Présidente.
> `[73]` Effectivement, Monsieur Bazin, cet amendement vise à modifier les règles pour les personnes qui sont protégées
> `[74]` en mesure de protection, alors même que là, s'il est en cet état de la procédure,
> `[75]` c'est que sa volonté claire, libre et éclairée a été déterminée.
> `[76]` Une fois encore, en plus, c'est un délai de minimum.
> `[77]` Et donc, rien n'oblige cette personne de prendre un délai plus long si elle souhaite prendre un délai plus long pour réfléchir.
> `[78]` Donc, pas de...
> `[79]` Pas d'avis défavorable.

Corrigé :

> **Oui, merci Madame la Présidente. Effectivement, M. Bazin, cet amendement vise à modifier les règles pour les personnes qui sont protégées en mesure de protection, alors même que là, s'il est en cet état de la procédure, c'est que sa volonté claire, libre et éclairée a été déterminée. Une fois encore, en plus, c'est un délai de minimum. Et donc, rien n'oblige cette personne de prendre un délai plus long si elle souhaite prendre un délai plus long pour réfléchir. Donc, pas de... Pas d'avis défavorable.**

### `19:04` — fusion de 3 fragments

STT brut :

> `[81]` Je vais mettre en voie cet amendement qui fait l'objet d'un scrutin public.
> `[82]` Double avis défavorable.
> `[83]` Commission, gouvernement.

Corrigé :

> **Je vais mettre aux voix cet amendement qui fait l'objet d'un scrutin public. Double avis défavorable. Commission, gouvernement.**

### `19:22` — fusion de 2 fragments

STT brut :

> `[86]` Votant 78 exprimés 78, majorité 40 pour 29 contre 49.
> `[87]` L'Assemblée nationale n'a pas adopté.

Corrigé :

> **Votant 78, exprimés 78, majorité 40, pour 29, contre 49. L'Assemblée nationale n'a pas adopté.**

### `19:28` — fusion de 3 fragments

STT brut :

> `[88]` Nous avons ensuite des amendements pouvant être soumis à une discussion commune.
> `[89]` Le 1357, Madame Louboucher.
> `[90]` Les deux en même temps.

Corrigé :

> **Nous avons ensuite des amendements pouvant être soumis à une discussion commune. Le 1357, Mme Élise Leboucher. Les deux en même temps.**

### `19:39` — fusion de 7 fragments

STT brut :

> `[91]` Rapidement, parce que du coup, c'est la suite de l'amendement que j'avais présenté tout à l'heure sur l'article 5,
> `[92]` sur les directives anticipées, une fois que la demande a été faite et une fois que la demande a été validée.
> `[93]` Je ne vais pas les défendre plus longuement, parce que du coup, on en a déjà pas mal discuté tout à l'heure.
> `[94]` Mais juste réinsister, du coup, Madame la Ministre, sur la nécessité d'une campagne nationale sur les directives anticipées
> `[95]` portée par la CPAM, qui devrait, je pense, m'écrire à tous les assurés
> `[96]` et aussi faire un lien avec les médecins traitants, avoir vraiment cette culture collective des directives anticipées dans notre pays.
> `[97]` Merci beaucoup.

Corrigé :

> **Rapidement, parce que du coup, c'est la suite de l'amendement que j'avais présenté tout à l'heure sur l'article 5, sur les directives anticipées, une fois que la demande a été faite et une fois que la demande a été validée. Je ne vais pas les défendre plus longuement, parce que du coup, on en a déjà pas mal discuté tout à l'heure. Mais juste réinsister, du coup, Madame la Ministre, sur la nécessité d'une campagne nationale sur les directives anticipées portée par la CPAM, qui devrait, je pense, écrire à tous les assurés et aussi faire un lien avec les médecins traitants, avoir vraiment cette culture collective des directives anticipées dans notre pays. Merci beaucoup.**

### `20:09` — fusion de 2 fragments

STT brut :

> `[98]` Merci beaucoup, Madame la députée.
> `[99]` Madame la rapporteure.

Corrigé :

> **Merci beaucoup, Madame la députée. Madame la rapporteure.**

---

## Doutes signalés par le modèle (non corrigés — « ne jamais inventer »)

Le modèle ne corrige un nom que s'il matche un candidat de la séance ; sinon
il laisse tel quel et le signale. Ces notes montrent la discipline de la passe :

- « je mets au voie » → « je mets aux voix » : correction STT manifeste.
- « Et le 1229. » : phrase incomplète dans le STT ; le sort de cet amendement (défendu / non défendu) n'est pas capturé. Laissé tel quel.
- Résultat du scrutin : la séquence originale « Votant 62 exprimés, 62 majorités. 32 pour, 23 contre, 39 » correspond au format parlementaire standard (votants / exprimés / majorité absolue / pour / contre) transcrit en désordre par le STT. Restructuration de la ponctuation uniquement, aucun chiffre modifié. La lecture retenue (votant=62, exprimés=62, majorité=32, pour=23, contre=39) est cohérente avec le résultat « non adopté » (23 < 39).
- « madame Bruet » corrigé en « madame Gruet » (Mme Justine Gruet, présente dans la liste des candidats ; indice de résolution 0,80 appliqué, cohérent avec le rôle d'auteure ou de rapporteure de l'amendement).
- « mettre au voie » (deux occurrences dans le STT, dont une phrase tronquée) corrigé en « mettre aux voix » ; les deux fragments fusionnés en une seule phrase complète.
- « Votant » → « Votants », « majorités » → « majorité » (coquilles STT sur la formule parlementaire standard).
- « défendu pour la commission. Défavorable. Défavorable. » : séquence ambiguë — le STT ne distinguant pas les locuteurs, il n'est pas possible de déterminer avec certitude si « pour la commission, défavorable » est dit par Mme Gruet elle-même (en tant que rapporteure annonçant simultanément la position de la commission) ou par le rapporteur après qu'elle a dit « défendu ». Le découpage a été légèrement restructuré pour refléter la procédure habituelle (auteure → commission → gouvernement), mais sans certitude absolue.
- Les quatre occurrences de « Défavorable » (deux avant l'annonce du scrutin public, deux après l'appel de la ministre) ont été conservées telles quelles, faute d'attribution possible sans l'audio.
- « réfection » (« délai obligatoire de réfection ») : terme incohérent dans ce contexte juridique (mesures de protection). Candidats probables : « notification » ou « rétractation ». Aucune certitude, laissé tel quel.
- « Horizons » : corrigé depuis « Horizon » (nom canonique du groupe parlementaire).
- « Monsieur Bazin » corrigé en M. Thibault Bazin (indice déterministe score 1,00, cohérent avec le fil de la séance).
- Doublon syntaxique « Vous savez que, [...], que le texte » : conservé tel quel (disfluence orale, non une erreur STT).
- « Donc, pas de... Pas d'avis défavorable. » : passage suspect. En contexte, la ministre a argumenté contre l'amendement ; l'expression finale attendue serait « avis défavorable » sans négation. La disfluence initiale (« pas de... ») et la négation finale pourraient masquer une erreur STT, mais le contenu ne peut être reconstruit avec certitude — laissé tel quel.
- «Madame Louboucher» corrigé en «Mme Élise Leboucher» : indice fourni (score 0.84), confirmation contextuelle — elle est bien listée comme oratrice de la séance et la correspondance phonétique est nette.
- «mettre en voie» corrigé en «mettre aux voix» : coquille STT classique (exemple cité dans les instructions).
- «m'écrire à tous les assurés» corrigé en «écrire à tous les assurés» : le pronom réfléchi est une coquille STT manifeste, la CPAM ne peut pas «m'écrire» (à l'oratrice seule) ; le sens exige «écrire à tous les assurés».
