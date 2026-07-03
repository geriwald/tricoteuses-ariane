# Résolution des référentiels stables (canutes)

> **MAJ 2026-06-29 — chemin de prod = API REST, pas le MCP.** Un service (`tricoteuses-ariane`)
> ne peut pas dépendre d'un MCP OAuth interactif. La résolution machine-to-machine passe par
> l'**API REST Tricoteuses Parlement** : `https://parlement.tricoteuses.fr` (HTTP nu, sans auth,
> hors Anubis — vérifié). Endpoints `/acteurs`, `/organes`, `/amendements` filtrent par
> `?uid[]=` (batch, plafond ~25 par appel) ; `/documents` par `?numNotice=<bibard>&legislature=17`
> (le filtre `?uid=` y est cassé). Champs déjà aplatis (`acteurRefUid`, `groupeParlementaireUid`,
> `numeroLong`, `divisionTitre`, `typeLibelle`…), pas besoin du `data` JSONB. Implémenté dans
> `spikes/2026-06-23-ttv-streaming-identification/artifacts/scripts/resolve_referential.py`.
> Le SQL Moulineuse ci-dessous reste valable comme **méthode d'exploration / vérification**,
> mais n'est plus le chemin de production.

Comment résoudre, depuis les clés portées par les flux live (dérouleur, NVS), les
**référentiels stables** de l'open data retravaillé par Tricoteuses (base `canutes`,
schéma `assemblee`). Historique : via le MCP **Moulineuse** (exploration). Tout ci-dessous
est de **lecture première main** : requêtes exécutées le 2026-06-26 (OAuth Moulineuse confirmé
fonctionnel), clés issues de la capture réelle de la séance « FIN DE VIE » (texte 2915).

## Orateur / auteur → acteur canonique `PA…` (#9) — trivial

**`uid acteur = "PA" + depute_tribun_id`.** Les `depute_tribun_id` du dérouleur et
les `<speaker><url>` du NVS sont l'identifiant Tribun ; l'acteur open data se
déduit par simple préfixage. Vérifié : **136/136** tribun_id de la capture résolvent.

```sql
SELECT data->>'uid' AS uid,
       data->'etatCivil'->'ident'->>'civ'    AS civ,
       data->'etatCivil'->'ident'->>'prenom' AS prenom,
       data->'etatCivil'->'ident'->>'nom'    AS nom
FROM assemblee.acteurs
WHERE data->>'uid' = ANY (SELECT 'PA' || x FROM unnest($tribun_ids::text[]) AS x);
```

Ex. `depute_tribun_id=794762` → `PA794762` (Mme Sandrine Dogor-Such). `assemblee.acteurs` = 3115 lignes.

Portée : ça résout l'**auteur d'amendement** (porté par le dérouleur) gratuitement.
Le trou réel du #9 reste l'orateur **au micro** (≠ auteur d'amendement : rapporteur,
ministre, président, rappel au règlement), qu'aucune base ne porte et que seule
l'attribution orale produit.

## Amendement → texte, auteur, division

Clé = `ligne_amendement_uid` du dérouleur, jointe sur `assemblee.amendements` (`data->>'uid'`).

```sql
SELECT data->>'uid' AS uid,
       data->'signataires'->'auteur'->>'acteurRef'          AS auteur_pa,
       data->'signataires'->'auteur'->>'groupePolitiqueRef' AS groupe_po,
       data#>>'{pointeurFragmentTexte,division,titre}'       AS division
FROM assemblee.amendements WHERE data->>'uid' = $uid;
```

Ex. `AMANR5L17PO838901BTC2915P0D1N000242` → auteur `PA794762`, groupe `PO845401`,
division « Article 6 ». Volumétrie totale du texte **2915** en base (mesurée 2026-06-29) :
**2404** amendements portant `BTC2915` toutes provenances (`uid LIKE '%BTC2915%'`,
5535 kB JSON), dont **1836** déposés à l'organe AN `PO838901`. Mais le snapshot de rejeu
ne porte **pas** ce périmètre large : il résout uniquement les clés effectivement présentes
dans le record capturé (les amendements réellement appelés en séance + leurs auteurs/groupes),
par requête `?uid[]=` exacte sur l'API REST. Pour la séance FIN DE VIE, cela donne **702
amendements résolus, ≈ 132 ko** (cf. spec mockup, section « Referential snapshot »), pas
les 2404 de la base. L'`acteurRef` confirme le pont PA indépendamment ; le
`groupePolitiqueRef` (`PO…`) se résout sur `assemblee.organes` (requis pour le snapshot).
Note : le **sort en séance** n'est PAS ici (open data post-consolidé) — il vient du live
Eliasse (`sortEnSeance`).

## Texte / dossier (Eloi / Legis)

Clé = `texte_bibard` du dérouleur (ex. 2915), sur `assemblee.documents`. Les uid
sont typés : `PIONANR5L17BTC2915` (proposition de loi, texte de commission),
`RAPPANR5L17B2915` (rapport). Le titre n'est pas en clé racine `titrePrincipal`
(champ exact à confirmer) — non bloquant, le dérouleur porte déjà `phase_libelle`.

## Pour le bundle de rejeu

Les référentiels sont **stables** → snapshot unique des clés résolues, hors horloge de
causalité (cf. spec mockup B-bricks). En production, la résolution passe par l'**API REST
Tricoteuses Parlement** (HTTP nu, sans auth, cf. bandeau MAJ en tête), appliquée aux clés
`_keys.json` d'une capture, produisant le snapshot self-contained. Les requêtes SQL
ci-dessus restent la méthode d'**exploration/vérification** via Moulineuse, pas le chemin
de prod.
