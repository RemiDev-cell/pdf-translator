# Handoff Projet

Date: 2026-05-27
Branche source de verite: `main`
Depot distant: `https://github.com/RemiDev-cell/pdf-translator.git`
Commit de reference avant versionnement de ce handoff: `eefc0b5 Merge branch 'main' into feature/ocr-layout-tsv`

## Etat De Reprise

`main` est maintenant la source de verite du projet et est alignee avec `origin/main`.

La branche `feature/ocr-layout-tsv` pointe sur le meme commit que `main` et reste disponible temporairement comme branche de securite. Les anciennes branches `feature/document-preview-command` et `feature/ocr-real-rendering` ont ete supprimees localement et a distance apres verification qu'elles etaient incluses dans `main`.

`HANDOFF.md` est maintenant un document versionne du depot. Il n'est plus seulement un fichier local de passage de relais.

Dernieres validations connues apres promotion:

- `./.venv/bin/python -m pytest -q` -> `132 passed`
- `./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --require-real-sources` -> `Probe matrix passed`
- `./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --include-local-inputs --require-real-sources --translator mock` -> `Probe matrix passed`
- `git diff --check` -> OK
- `data/output/` -> aucun fichier ecrit

Ne pas lancer la matrice `--include-local-inputs` avec le traducteur configure sans approbation explicite: les PDF locaux ignores peuvent contenir du texte prive qui serait envoye au backend de traduction configure.

## Distance Au Produit Final

Le projet est tres avance comme socle technique de recherche et de validation. Il sait inspecter des PDF, router les pages natives/OCR, generer des diagnostics riches, produire des previews natives, analyser des regions OCR, rendre un prototype OCR in-place garde, et verifier des invariants de recomposition sur une matrice reelle.

Il n'est pas encore une version finalisee et 100% fonctionnelle au sens produit. La difference majeure est l'absence d'un chemin final explicite qui prenne un PDF utilisateur en entree et ecrive un PDF traduit final dans `data/output/` avec une politique stable, documentee et testee.

Estimation qualitative:

- environ 60-70% du socle technique exploratoire est en place;
- environ 30-40% du produit final utilisateur est livre;
- la valeur principale actuelle est l'inspectabilite et les garde-fous, pas encore la production bout-en-bout.

Pour atteindre une version 100% fonctionnelle, il faut transformer les prototypes et diagnostics en un pipeline de sortie finalise, tout en gardant les garde-fous qui ont rendu le systeme fiable.

## Etat Fonctionnel Actuel

Ce qui est solide:

- extraction PyMuPDF structuree et representation intermediaire;
- protection des placeholders techniques;
- traduction locale via LM Studio avec batchs, validation et fallbacks;
- diagnostics de roles, zones de page, ordre de lecture, groupes de mise en page et readiness overlay;
- preview d'overlay natif avec politiques `ready`, `soft_review`, `hard_review`, `blocked`;
- routing entre pages natives, hybrides et OCR;
- workflow OCR experimental avec Tesseract ou mock;
- fusion native/OCR, plans de remplacement mixtes et recommandations de rendu OCR;
- prototype OCR in-place garde par la readiness OCR;
- artefacts HTML de recomposition avec zones autorisees et verdicts;
- matrice de probes OCR, y compris fond sombre et fond clair;
- tests unitaires et integration locale consistants.

Ce qui manque pour un produit final:

- commande finale explicite, par exemple `translate-document`;
- ecriture controlee dans `data/output/`;
- politique stable de sortie finale sur document complet;
- promotion controlee de l'OCR in-place hors prototype;
- qualite linguistique robuste et mesurable;
- glossaires adaptatifs utilisateur/domaine/document;
- prise en charge robuste des tableaux;
- strategie fiable pour formules, notations et diagrammes;
- validation multi-documents plus large;
- performance, reprise, logs structures et packaging de release.

## Contraintes A Conserver

- Garder `document-preview` comme entree de revue tant que la sortie finale n'est pas explicitement introduite.
- Ne pas ecrire dans `data/output/` depuis des commandes de debug ou de preview.
- Ne pas promouvoir l'OCR in-place par defaut sans validation visuelle et invariants de recomposition.
- Continuer a traiter `data/debug/` comme l'audit trail principal.
- Ne pas optimiser pour un seul PDF: les probes couvrent des cas complementaires.
- Garder Tesseract et le traducteur configure pour les validations serieuses; utiliser `--translator mock` pour les entrees locales sensibles ou le debug rapide.
- Preserver les decisions de readiness: mieux vaut bloquer ou annoter qu'ecrire un rendu final trompeur.

## Roadmap Operationnelle

### 1. Stabiliser Le Socle `main`

Objectif: rendre `main` durablement exploitable par une equipe.

Travail recommande:

- garder `main` comme base de toutes les nouvelles branches;
- conserver `feature/ocr-layout-tsv` quelques jours comme branche de securite, puis la supprimer quand l'equipe est confortable;
- actualiser le README et ce handoff lorsqu'une decision structurante change;
- reduire progressivement les fichiers non essentiels generes localement (`.DS_Store`, caches, artefacts ignores) sans toucher aux donnees utilisateur;
- etablir une routine de validation minimale avant chaque merge.

Livrables attendus:

- README et handoff synchronises;
- checklist de validation courte;
- convention de branches claire: `feature/<sujet>` depuis `main`;
- aucun artefact final ecrit hors `data/output/`.

Critere de sortie:

- une personne nouvelle peut cloner le depot, lire README + handoff, lancer les tests et comprendre quel travail commencer.

Risques:

- continuer a melanger debug, preview et production;
- laisser `feature/ocr-layout-tsv` redevenir une branche active parallele a `main`.

### 2. Creer Une Commande Finale Explicite `translate-document`

Objectif: introduire le premier vrai chemin utilisateur finalise, distinct des previews.

Travail recommande:

- ajouter une commande CLI explicite, par exemple:

```bash
./.venv/bin/python -m pdf_translator.cli translate-document data/input/myfile.pdf
```

- ecrire le PDF traduit dans `data/output/`;
- produire aussi un resume final lisible et un resume JSON;
- reutiliser le routing actuel pour choisir natif, fusion native/OCR, annotation ou blocage;
- refuser de produire un PDF final silencieusement si trop de pages sont `blocked` ou `hard_review`;
- garder tous les diagnostics complets dans `data/debug/`.

Livrables attendus:

- commande CLI;
- fonction pipeline dediee, separee de `run_document_preview`;
- tests unitaires et integration sur PDF synthetiques;
- resume final avec pages appliquees, pages annotees, pages bloquees, OCR in-place applique ou non.

Critere de sortie:

- un PDF simple born-digital peut etre traduit et ecrit dans `data/output/` avec un resume expliquant toutes les decisions.

Risques:

- brancher trop vite la logique debug dans une sortie finale;
- masquer des pages non fiables au lieu de les bloquer explicitement.

### 3. Unifier Preview Et Production Sans Divergence

Objectif: faire de `document-preview` une representation fidele du comportement final, sans qu'elle devienne le chemin de production.

Travail recommande:

- extraire les politiques communes de rendu dans des modules non-debug lorsque leur comportement est stabilise;
- garder les fonctions de visualisation et HTML dans les modules debug;
- faire partager les memes plans et decisions a `document-preview` et `translate-document`;
- documenter les correspondances: `applied`, `annotated`, `appendix`, `blocked`, `skipped_fit_risk`;
- conserver les artefacts `data/debug/` pour expliquer tout PDF final.

Livrables attendus:

- politique de sortie commune;
- tests qui comparent decisions preview et decisions production;
- documentation des decisions finales.

Critere de sortie:

- une page qui apparait appliquee, annotee ou bloquee dans `document-preview` se comporte pareil dans `translate-document`.

Risques:

- creer deux pipelines qui se ressemblent mais divergent;
- perdre l'explicabilite en deplacant trop vite le code hors debug.

### 4. Promouvoir Controlee De L'OCR In-Place

Objectif: permettre l'OCR in-place dans une sortie finalisee uniquement quand les conditions sont fortes.

Travail recommande:

- garder `ocr-inplace-preview --review-final-like` comme outil de revue explicite;
- promouvoir l'OCR in-place dans `translate-document` seulement pour `ready_for_image_overlay`;
- conserver `side_annotation_review`, `manual_review` et `blocked` comme sorties non destructives;
- etendre la matrice actuelle aux cas suivants: fond sombre, fond clair, texte dense, texte court, image contrainte, scan pur, hybride local;
- exiger `outside_allowed_ratio=0.0` sur les cas final-like avant promotion.

Livrables attendus:

- option ou politique de sortie finale OCR;
- invariants de matrice renforces;
- revue HTML lisible pour toute page OCR modifiee;
- tests de non-regression sur `03_mixed_native_ocr_image` et `04_mixed_light_ocr_image`.

Critere de sortie:

- OCR in-place est applique dans `translate-document` sur des cas simples et propres, tout en preservant les annotations/review pour les cas incertains.

Risques:

- sur-apprendre sur deux probes synthetiques;
- degradation visuelle non detectee par les seuls compteurs de pixels;
- traduction OCR trop longue qui rentre techniquement mais devient illisible.

### 5. Qualite Linguistique Et Glossaires Adaptatifs

Objectif: passer d'une traduction locale acceptable a une traduction controlee, mesurable et ameliorable.

Travail recommande:

- definir une couche d'evaluation de segment: placeholders, unites, longueur relative, conservation des nombres, hallucinations evidentes;
- permettre plusieurs backends/modeles de traduction;
- concevoir des glossaires auditables: general, domaine, document, utilisateur;
- ajouter une selection explicite de glossaire par execution;
- garder les glossaires deterministes avant d'introduire une logique RAG;
- ajouter des rapports de qualite linguistique separes des rapports de recomposition.

Livrables attendus:

- schema de glossaire;
- moteur de matching deterministe;
- tests de preservation terminologique;
- rapport de qualite par document.

Critere de sortie:

- l'equipe peut imposer une terminologie et verifier automatiquement qu'elle est respectee sur les segments traduits.

Risques:

- confondre glossaire terminologique et contexte generique;
- rendre la traduction moins fluide en surcontraignant les segments;
- ajouter un modele plus puissant sans garde-fous de validation.

### 6. Matrices Multi-Documents Et Criteres Visuels

Objectif: remplacer les validations ponctuelles par une validation representative du produit.

Travail recommande:

- transformer la matrice OCR en matrice generale de documents;
- couvrir born-digital simple, scientifique dense, slides, formulaires, tableaux, OCR pur, hybride, scan contraint;
- definir des seuils par type de document: pages appliquees, pages bloquees, changements hors zones, annotations attendues;
- produire un index HTML de revue pour toutes les sorties;
- garder les PDF utilisateur sensibles hors Git.

Livrables attendus:

- script de matrice generale;
- fixtures synthetiques versionnees;
- support d'entrees locales ignorees;
- rapport HTML global.

Critere de sortie:

- une regression de routage, recomposition ou readiness est detectee avant merge sur `main`.

Risques:

- matrice trop lente pour etre lancee souvent;
- dependance excessive a des documents locaux non versionnes;
- criteres visuels trop faibles pour capturer la lisibilite.

### 7. Cas Difficiles: Tableaux, Formules, Diagrammes, Multi-Colonnes

Objectif: traiter les classes de PDF scientifiques qui feront echouer un pipeline generaliste.

Travail recommande:

- tableaux: detecter cellules, traduire cellule par cellule, conserver lignes et colonnes;
- formules: proteger ou ignorer selon contexte, eviter toute traduction destructrice;
- diagrammes: distinguer labels natifs, labels OCR, bruit graphique et captions;
- multi-colonnes: renforcer l'ordre de lecture et eviter les fusions inter-colonnes;
- ajouter des fixtures dediees pour chaque categorie.

Livrables attendus:

- readiness specifique par type de region;
- tests ciblant les cas difficiles;
- politique de blocage explicite quand la fidelite ne peut pas etre garantie.

Critere de sortie:

- le pipeline sait soit reconstruire proprement ces cas, soit les bloquer/annoter clairement sans corruption silencieuse.

Risques:

- complexite heuristique difficile a maintenir;
- tentation de tout traiter en OCR;
- ordre logique correct mais rendu visuel incorrect, ou inversement.

### 8. Industrialisation Et Release

Objectif: transformer le prototype local en outil exploitable de facon repetitive.

Travail recommande:

- logs structures par document et par page;
- reprise apres echec: cache OCR, cache traduction, reprise par page;
- profils de configuration: rapide, qualite, debug, release;
- gestion claire des erreurs utilisateur;
- documentation d'installation et d'exploitation;
- packaging et versioning;
- checklist de release incluant tests, matrices, revue visuelle et verification `data/output`.

Livrables attendus:

- commande de release locale;
- documentation d'exploitation;
- changelog;
- politique de version;
- jeu de tests/matrices defini comme gate de release.

Critere de sortie:

- une equipe peut executer le pipeline sur plusieurs documents, reprendre apres incident, comparer les sorties, et livrer une version avec confiance.

Risques:

- optimiser la performance avant de figer les comportements;
- rendre les logs volumineux mais peu utiles;
- ne pas separer clairement donnees locales sensibles et artefacts versionnables.

## Prochaine Etape Recommandee

La prochaine tranche la plus pertinente est la conception puis l'implementation de `translate-document`.

Cette commande doit etre explicite, ecrire dans `data/output/`, reutiliser les garde-fous existants, et produire un resume final. Elle ne doit pas changer le comportement par defaut de `document-preview`.

Plan court suggere:

1. definir le contrat CLI et les chemins de sortie;
2. implementer un premier chemin born-digital natif avec overlay fiable;
3. garder OCR en annotation ou blocage dans cette premiere version finale;
4. ajouter ensuite OCR in-place uniquement pour les cas `ready_for_image_overlay`;
5. etendre les matrices pour couvrir la sortie finale.

## Sources De Verite

- `README.md`: vue generale, commandes, limites et workflow courant.
- `HANDOFF.md`: roadmap operationnelle et priorites de reprise.
- `src/pdf_translator/pipeline.py`: orchestration de preview actuelle.
- `src/pdf_translator/compose/overlay.py`: overlay natif et plans de remplacement.
- `src/pdf_translator/ocr/debug.py`: workflow OCR, prototype in-place, HTML de recomposition.
- `scripts/run_ocr_inplace_probe_matrix.py`: invariants OCR in-place.
- `tests/test_pipeline.py`, `tests/test_overlay.py`, `tests/test_ocr_debug.py`, `tests/test_ocr_probe_matrix.py`: contrats comportementaux principaux.

## Commandes De Validation Courantes

Validation rapide:

```bash
./.venv/bin/python -m pytest -q
```

Validation OCR serieuse sans entrees locales ignorees:

```bash
./.venv/bin/python scripts/generate_test_pdfs.py
./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --require-real-sources
```

Validation OCR avec entrees locales sensibles en mock:

```bash
./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --include-local-inputs --require-real-sources --translator mock
```

Validation avant release future:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --require-real-sources
git diff --check
```
