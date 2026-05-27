# pdf-translator

`pdf-translator` est un pipeline Python en cours de développement pour traduire des PDF scientifiques du français vers l'anglais tout en préservant autant que possible la structure et la fidélité visuelle.

L'objectif à long terme n'est pas seulement la traduction du texte, mais la reconstruction fidèle du PDF :

- préserver la mise en page
- préserver les figures, diagrammes et structures de page
- protéger les tokens techniques et les fragments sensibles
- préparer un futur workflow d'overlay / recomposition en place

La version actuelle est un prototype local `accuracy-first`. Elle est volontairement conservatrice, inspectable, et plus lente qu'un système de production.

## État Actuel

Ce qui fonctionne déjà :

- extraction PDF structurée avec PyMuPDF
- représentation intermédiaire (IR) en JSON
- protection par placeholders pour les fragments techniques
- traduction locale via LM Studio
- traduction par lots avec validation et fallbacks
- audit des blocs répétés / éléments de chrome de slides
- artefacts de diagnostic `overlay-ready` et `pre-overlay`, avec zones de page, ordre de lecture, groupes de mise en page et sévérité de readiness
- previews visuelles d'overlay sur des pages sélectionnées
- prototype stabilisé d'overlay sur texte natif pour des pages réelles représentatives
- branche OCR expérimentale pour le texte en images raster, avec crops de debug, revue OCR, preview de traduction mixte native/OCR, et sortie d'overlay diagnostic

Ce qui n'est pas encore terminé :

- reconstruction finale du PDF traduit
- overlay de production sur document complet
- recomposition OCR de production pour le texte intégré dans des images raster
- glossaires adaptatifs pilotés par l'utilisateur et les documents
- gestion avancée des formules / équations
- reconstruction robuste des tableaux
- performances et passage à l'échelle de niveau production

## Pourquoi Ce Projet Existe

De nombreux PDF scientifiques sont difficiles à bien traduire parce qu'ils contiennent :

- des mises en page multi-colonnes
- des en-têtes et pieds de page répétés
- des diagrammes et callouts
- des images contenant du texte intégré
- des équations, notations et labels symboliques
- des decks de slides exportés avec une structure visuelle dense

Ce projet est construit par étapes :

1. établir un prototype local fiable
2. valider l'extraction et la traduction sur des documents réels
3. préparer une sélection de régions compatible avec un futur overlay
4. passer à un runtime plus robuste et à de meilleurs modèles
5. monter en charge une fois l'architecture correcte

## Organisation Du Dépôt

```text
pdf-translator/
├── .env.example
├── HANDOFF.md
├── README.md
├── data/
│   ├── input/
│   ├── output/   # réservé aux futures sorties finalisées
│   └── debug/    # previews, probes et artefacts de revue visuelle actuels
├── scripts/
├── src/pdf_translator/
│   ├── compose/
│   ├── extract/
│   ├── ocr/
│   ├── qa/
│   ├── routing.py
│   └── translate/
└── tests/
```

## Reprise Projet / Handoff

Pour reprendre le projet en équipe, lire d'abord ce README pour comprendre le périmètre, les commandes et les limites actuelles, puis lire `HANDOFF.md`.

`HANDOFF.md` est maintenant versionné dans le dépôt. Il décrit l'état réel de `main`, la distance restante jusqu'à une version finalisée, les validations connues, les contraintes à conserver et la roadmap opérationnelle recommandée.

## Stack Locale

Environnement local de référence utilisé pendant le développement :

- Python `3.9.6`
- environnement virtuel local dans `.venv`
- serveur local LM Studio
- modèle testé : `translategemma-4b-it`
- base API locale : `http://localhost:4000/v1`
- binaire Tesseract OCR optionnel pour le workflow OCR expérimental

## Installation

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Pour le workflow OCR expérimental sur macOS :

```bash
brew install tesseract
```

## Configuration

Les paramètres principaux se trouvent dans `.env`.

Exemple :

```env
PDF_TRANSLATOR_MODEL_BACKEND=lmstudio
PDF_TRANSLATOR_API_BASE=http://localhost:4000/v1
PDF_TRANSLATOR_API_KEY=lm-studio
PDF_TRANSLATOR_MODEL_NAME=translategemma-4b-it
PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS=45
PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES=1
PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS=160
PDF_TRANSLATOR_BATCH_MAX_SEGMENTS=2
PDF_TRANSLATOR_BATCH_MAX_CHARS=800
PDF_TRANSLATOR_OCR_BACKEND=auto
PDF_TRANSLATOR_OCR_TESSERACT_BIN=tesseract
```

## Paramètres Stables Recommandés

Pour la machine locale actuelle, le profil le plus stable observé jusqu'ici est :

- `PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS=45`
- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES=1`
- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS=160`
- `PDF_TRANSLATOR_BATCH_MAX_SEGMENTS=2`
- `PDF_TRANSLATOR_BATCH_MAX_CHARS=800`

Ces valeurs privilégient la fiabilité plutôt que la vitesse.

## Commandes Principales

Inspecter un PDF et écrire la représentation intermédiaire :

```bash
./.venv/bin/python -m pdf_translator.cli inspect data/input/myfile.pdf
```

Lancer un audit ciblé sur des pages sélectionnées :

```bash
./.venv/bin/python -m pdf_translator.cli audit-sample data/input/myfile.pdf --pages "1,3,10,22"
```

Générer les blocs candidats `overlay-ready` :

```bash
./.venv/bin/python -m pdf_translator.cli overlay-ready data/input/myfile.pdf --pages "1,3,10,22"
```

Générer les régions `pre-overlay` avec leurs bounding boxes :

```bash
./.venv/bin/python -m pdf_translator.cli pre-overlay data/input/myfile.pdf --pages "1,3,10,22"
```

Générer des diagnostics visuels d'overlay :

```bash
./.venv/bin/python -m pdf_translator.cli overlay-preview data/input/myfile.pdf --pages "1,3,10,22"
```

Générer une preview de traduction lisible :

```bash
./.venv/bin/python -m pdf_translator.cli translation-preview data/input/myfile.pdf --pages "10,22"
```

Lancer le workflow OCR expérimental sur un PDF hybride ou scanné :

```bash
./.venv/bin/python -m pdf_translator.cli ocr-experiment data/input/supportpourocr01.pdf --backend tesseract
```

Essayer une preview de traduction OCR au niveau page sans tenter de recomposition d'image :

```bash
./.venv/bin/python -m pdf_translator.cli ocr-page-preview data/input/supportpourocr01.pdf --pages 1 --backend tesseract
```

Générer une preview multi-pages du document pour revue, avec overlays natifs prudents et régions OCR annotées :

```bash
./.venv/bin/python -m pdf_translator.cli document-preview data/input/supportpourocr01.pdf --pages 1-3 --backend tesseract
```

Générer une preview routée du document. Les pages uniquement natives utilisent la chaîne d'overlay natif ; les pages avec candidats OCR utilisent la chaîne de fusion native/OCR :

```bash
./.venv/bin/python -m pdf_translator.cli document-preview data/input/myfile.pdf --pages "1-3" --backend tesseract
```

Générer directement une preview d'overlay sur texte natif lorsque l'OCR n'est pas nécessaire :

```bash
./.venv/bin/python -m pdf_translator.cli native-preview data/input/myfile.pdf --pages "1-3"
```

## Artefacts De Debug

`data/output/` est réservé aux futurs PDF finalisés et peut ne pas exister localement, car Git ne suit pas les dossiers vides. Le workflow de recomposition actuel écrit ses artefacts inspectables dans `data/debug/`.

Le pipeline écrit des artefacts intermédiaires utiles dans `data/debug/`, notamment :

- `document_ir.json`
- rapports d'audit
- rapports `overlay-ready` avec raisons de candidature/exclusion, métriques de géométrie, résumés de zones de page, diagnostics d'ordre de lecture, groupes de mise en page et statut de readiness
- rapports `pre-overlay`
- PDF et PNG de preview overlay
- fichiers de preview de traduction
- plans de remplacement natifs et résumés d'overlay avec politiques d'application par page et décisions de rendu dérivées de la readiness overlay
- rapports de candidats OCR, crops, manifests et rapports de revue
- plans de fusion native/OCR, previews de traduction, plans de remplacement, rapports de stratégie et PDF d'overlay diagnostic
- résumés de readiness OCR qui classent les régions OCR avant toute recomposition d'image in-place
- fichiers HTML de revue de recomposition OCR in-place avec images source/prototype, zones source/annotation/appendix explicites, métriques de changement par page, et verdicts `clean` / `expected_annotation_changes` / `unexpected_outside_changes`

Ces artefacts sont au coeur du workflow actuel et rendent le système beaucoup plus simple à inspecter et à améliorer.

## Jalon V1 Stabilisé

Le jalon actuel est un prototype stabilisé `texte natif + overlay`.

Cela signifie que le projet peut maintenant :

- détecter et filtrer le chrome de slides, les en-têtes / pieds de page répétés, le bruit de diagramme et les numéros de page
- sélectionner des régions candidates à l'overlay depuis de vrais PDF
- classer la readiness overlay en `ready`, `soft_review`, `hard_review` ou `blocked` avant recomposition
- traduire de nombreux labels scientifiques courts via un glossaire contrôlé
- traduire les blocs narratifs avec des fallbacks conservateurs
- traduire de petits labels structurels via des fallbacks déterministes de native-preview
- générer des plans de remplacement avec niveaux de risque
- rendre des prototypes d'overlay directement sur les pages PDF originales

La readiness overlay contrôle maintenant l'application de l'overlay natif :

- les pages `ready` utilisent `apply_overlay`
- les pages `soft_review` utilisent `apply_overlay_with_soft_review` et restent rendues pour validation visuelle
- les pages `hard_review` utilisent `skip_overlay_hard_review`
- les pages `blocked` utilisent `skip_overlay_blocked`

Les pages ignorées produisent toujours la chaîne de diagnostic, mais leurs remplacements sont comptés comme considérés plutôt qu'appliqués.
Les résumés d'overlay natif expliquent aussi chaque remplacement considéré avec `applied`, `skipped_page_policy`, `skipped_status`, `skipped_apply_strategy` ou `skipped_fit_risk`.
Les régions de preview de traduction incluent maintenant `translation_method` et `translation_attempt_count`, afin de rattacher `skipped_status` à `model`, `glossary`, `outline_fallback`, `structural_fallback`, `timeout` ou à un comportement `skipped` volontaire.

Pages représentatives déjà validées sur le vrai deck scientifique exporté depuis PowerPoint :

- page `3` : labels denses + paragraphes explicatifs
- page `10` : bandeau de titre + page de diagramme bruitée
- page `22` : slide pédagogique structurée
- page `34` : slide explicative narrative
- page `120` : slide pédagogique courte
- page `160` : titre + labels scientifiques de diagramme

Limite importante de ce jalon :

- il s'agit d'un bon `prototype d'overlay sur texte natif`
- ce n'est pas encore le moteur final de reconstruction de production
- l'OCR et le texte dans les images sont maintenant explorés dans un workflow expérimental séparé, pas dans le chemin d'overlay de production

## Workflow OCR Expérimental

La branche OCR est volontairement séparée du chemin stabilisé d'overlay sur texte natif.

Elle prend actuellement en charge :

- la détection des blocs image comme candidats OCR pendant l'extraction PyMuPDF
- le crop des régions image candidates en fichiers PNG de debug
- l'exécution de l'OCR via Tesseract ou un backend mock
- la revue de qualité OCR et des caractères suspects
- la combinaison du texte natif et du texte OCR dans un plan de fusion
- la traduction de segments mixtes natifs/OCR
- la construction d'un plan de remplacement mixte avec stratégies explicites
- la recommandation indiquant si la sortie OCR doit rester une annotation latérale ou devenir un futur candidat d'overlay sur image
- la classification de la readiness OCR en `ready_for_image_overlay`, `side_annotation_review`, `manual_review` ou `blocked`
- le rendu d'un PDF diagnostic qui applique les remplacements natifs et annote les régions OCR en attente
- le rendu d'un prototype OCR in-place explicite et gardé pour les régions OCR classées comme prêtes
- l'explication des méthodes de traduction native/OCR et des décisions de rendu dans les résumés de debug

Le workflow en une commande est :

```bash
./.venv/bin/python -m pdf_translator.cli ocr-experiment data/input/supportpourocr01.pdf --backend tesseract
```

Le point d'entrée de revue recommandé est maintenant `document-preview`, qui écrit d'abord un rapport de routage puis délègue soit à la preview d'overlay natif, soit à la preview de fusion native/OCR.

Un prototype OCR in-place explicite peut être rendu à partir d'un plan de remplacement existant :

```bash
./.venv/bin/python -m pdf_translator.cli ocr-inplace-preview data/input/supportpourocr01.pdf --plan-json data/debug/supportpourocr01_document_preview_fusion_replacement_plan.json
```

La commande peut aussi générer d'abord le plan de fusion OCR :

```bash
./.venv/bin/python -m pdf_translator.cli ocr-inplace-preview data/input/supportpourocr01.pdf --pages 1 --backend tesseract
```

Pour obtenir un artefact de revue explicitement final-like qui masque les marqueurs OCR in-place tout en restant dans `data/debug/` :

```bash
./.venv/bin/python -m pdf_translator.cli ocr-inplace-preview data/input/supportpourocr01.pdf --pages 1 --backend tesseract --review-final-like
```

Sorties utiles :

- `data/debug/*_ocr_dry_run_manifest.json`
- `data/debug/*_ocr_dry_run_page_*_ocr_*.png`
- `data/debug/*_fusion_translation_preview.txt`
- `data/debug/*_fusion_replacement_plan.json`
- `data/debug/*_fusion_replacement_plan.txt`
- `data/debug/*_ocr_overlay_strategy.json`
- `data/debug/*_ocr_overlay_strategy.txt`
- `data/debug/*_ocr_page_translation_preview.json`
- `data/debug/*_ocr_page_translation_preview.txt`
- `data/debug/*_fusion_overlay_diagnostics.pdf`
- `data/debug/*_ocr_inplace_prototype.pdf`
- `data/debug/*_ocr_inplace_prototype.txt`
- `data/debug/*_ocr_inplace_prototype_page_*.png`
- `data/debug/*_ocr_inplace_final_like_prototype.pdf`
- `data/debug/*_ocr_inplace_final_like_prototype.txt`
- `data/debug/*_ocr_inplace_final_like_prototype_page_*.png`
- `data/debug/*_ocr_inplace_final_like_recomposition_review.html`

Limite OCR actuelle :

- le texte OCR peut être extrait, revu, traduit et inclus dans des artefacts de diagnostic
- les remplacements de texte natif peuvent toujours être prévisualisés via le chemin d'overlay
- les résumés de fusion/OCR exposent maintenant la méthode de traduction, le nombre de tentatives et les décisions de rendu par remplacement
- le rendu diagnostic OCR est piloté par la recommandation OCR finale : overlay image, annotation latérale ou revue manuelle
- la readiness OCR n'est toujours pas active dans `document-preview` ; la commande séparée `ocr-inplace-preview` l'utilise comme garde pour le rendu prototype in-place
- les régions OCR ne sont pas encore réécrites à l'intérieur de l'image scannée par le chemin de preview par défaut
- les longues traductions OCR sont actuellement recommandées comme annotations latérales lorsqu'elles ne tiennent pas de façon sûre dans la région image source

Valider le prototype OCR gardé sur les probes connues avec :

```bash
./.venv/bin/python scripts/generate_test_pdfs.py
./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --include-local-inputs --require-real-sources
```

La matrice de probes utilise le traducteur configuré et Tesseract par défaut. Utiliser `--translator mock` ou `--backend mock` seulement pour du debug rapide lorsque le modèle local ou le moteur OCR est indisponible. `--require-real-sources` fait échouer la validation si les PDF sources OCR attendus sont absents au lieu de retomber sur des PDF synthétiques de debug. Le run avec entrées locales inclut `data/input/essai_ocr_02.pdf` lorsqu'il est présent et rapporte sa route, sa readiness OCR, ses modes de rendu de recomposition, ses décisions de rendu et les chemins PDF/TXT/PNG/HTML générés.

Lorsqu'une probe applique réellement l'OCR in-place, la matrice rend aussi un artefact de revue final-like avec les marqueurs de revue OCR masqués. Elle valide que ce rendu final-like conserve les mêmes décisions de rendu, reste `clean`, ne change aucun pixel hors des zones autorisées, et rapporte `ocr_inplace_review_markers=False`. Les probes qui utilisent seulement des annotations latérales ou des appendices de revue manuelle déclarent le rendu final-like comme non applicable.

Les probes OCR in-place générées couvrent à la fois une image sur fond sombre (`03_mixed_native_ocr_image.pdf`) et une image sur fond clair (`04_mixed_light_ocr_image.pdf`), afin de vérifier les choix automatiques de fond et de couleur de texte dans les deux directions.

Le prototype OCR in-place écrit aussi `data/debug/*_ocr_inplace_recomposition_review.html` avec les images de page source/prototype et les métriques de recomposition par zone de rendu explicite : zones de remplacement source, zones d'annotation, zones d'appendix, changements hors zones autorisées, et verdict de page (`clean`, `expected_annotation_changes` ou `unexpected_outside_changes`).

Le prototype OCR in-place actuel vise la fidélité de recomposition, pas la qualité finale de traduction. Le texte traduit reste un input pour stresser l'ajustement de mise en page et les gardes de readiness ; le projet est destiné à être connecté plus tard à un modèle de traduction plus robuste.

## Entrées De Test

PDF synthétiques et réels actuellement utilisés :

- `docnavettepourtestsimple.pdf`
- `simple-fr.pdf`
- `scientifique-mixte.pdf`
- `layout-tricky.pdf`
- `supportpourocr01.pdf`
- `02_scanned_pure_ocr.pdf`
- `03_mixed_native_ocr_image.pdf`
- `04_mixed_light_ocr_image.pdf`

Des probes OCR locales supplémentaires peuvent être présentes mais sont volontairement ignorées par Git, par exemple `essai_ocr_02.pdf`.

Les PDF synthétiques peuvent être régénérés avec :

```bash
./.venv/bin/python scripts/generate_test_pdfs.py
```

## Protection Par Placeholders

Le pipeline protège actuellement :

- emails
- URLs
- longs hashes de commit
- dates ISO
- versions logicielles comme `x.y.z`

Cela aide à réduire la corruption accidentelle pendant la traduction.

## Futurs Glossaires Adaptatifs

Le pipeline devra à terme prendre en charge un ou plusieurs glossaires adaptatifs afin de rendre les traductions de plus en plus pertinentes.

Ce n'est pas encore implémenté. Le code actuel contient seulement un petit glossaire statique pour quelques labels scientifiques et phrases de slides contrôlés. L'orientation long terme est plus large :

- maintenir un glossaire général appris à partir des documents précédemment traduits
- permettre aux utilisateurs d'enrichir le glossaire manuellement à tout moment
- garder les entrées de glossaire inspectables et modifiables plutôt que cachées dans l'état d'un modèle
- prendre en charge des catégories de glossaire, comme des disciplines scientifiques ou des vocabulaires client/domaine
- laisser l'utilisateur choisir la portée active du glossaire pour une tâche de traduction

Exemples de choix futurs :

- utiliser seulement le glossaire général
- utiliser un ou plusieurs glossaires de catégories, comme biologie, mathématiques, physique, médecine ou administration
- combiner le glossaire général avec des catégories sélectionnées
- désactiver entièrement l'usage du glossaire pour une tâche

L'objectif est que l'outil devienne de plus en plus précis tout en restant contrôlable. Par exemple, un document de biologie devrait pouvoir utiliser une terminologie propre à la biologie, tandis qu'un document de mathématiques devrait pouvoir activer une couche terminologique différente.

Cette fonctionnalité doit être conçue comme une brique explicite du pipeline avant d'ajouter une approche augmentée par récupération. Les entrées de glossaire sont des contraintes terminologiques, pas du contexte générique. Une future couche de type RAG pourra être utile pour de très grands glossaires, des mémoires de traduction, des guides de style ou des notes de domaine, mais le premier besoin est un système de glossaire déterministe et auditable, que l'utilisateur peut sélectionner, enrichir et relire.

## Stratégie Sur Documents Réels

Le projet est actuellement validé sur deux types de documents réels :

- un deck pédagogique exporté depuis PowerPoint avec mise en page dense et nombreuses images
- un PDF hybride plus petit avec une qualité d'extraction moins prévisible

C'est volontaire :

- les PDF exportés depuis des slides sont une cible forte pour la préparation d'overlay
- les PDF hybrides sont utiles plus tard pour la préparation OCR et les tests de robustesse

## Limites Connues

- la sortie du modèle local peut encore être incohérente sur les blocs difficiles
- certaines régions longues nécessitent encore des fallbacks déterministes ou une aide de glossaire
- le support des glossaires est actuellement statique et limité ; les glossaires adaptatifs utilisateur/catégorie sont un travail futur
- l'OCR est expérimental et orienté debug, pas recomposition de production
- le texte de diagramme intégré dans les images n'est pas encore reconstruit en place
- la notation scientifique très chargée en formules nécessite encore une logique dédiée
- les heuristiques actuelles sont utiles, mais pas finales

## Roadmap

Court terme :

1. garder la v1 locale stable
2. continuer à valider la généralisation de l'overlay sur de nouvelles pages représentatives
3. valider le workflow OCR expérimental sur davantage de fixtures hybrides/scannées

Moyen terme :

1. passer à un runtime et à une pile de modèles plus robustes
2. réactiver et valider un groupement contextuel plus riche
3. concevoir le stockage adaptatif des glossaires, le matching, l'enrichissement utilisateur et la sélection de catégories
4. décider de la stratégie de rendu OCR : annotations latérales, overlay de région image, ou reconstruction d'image plus profonde

Long terme :

1. reconstruire fidèlement les PDF traduits
2. prendre en charge les diagrammes, figures et textes intégrés
3. prendre en charge des glossaires de traduction généraux et spécifiques à des domaines, s'améliorant continuellement
4. passer le pipeline à l'échelle pour des documents plus volumineux et de meilleures performances

## Développement

Lancer les tests avec :

```bash
./.venv/bin/python -m pytest
```

Le projet privilégie actuellement :

- la correction plutôt que la vitesse
- l'inspectabilité plutôt que l'opacité
- la transférabilité plutôt que le surapprentissage local

## Licence

Aucune licence n'a encore été ajoutée.
