# pdf-translator

Pipeline Python de traduction de PDF scientifiques FR -> EN avec preservation maximale de la structure utile a une future recomposition PDF.

## Etat actuel

La v1 locale sait deja faire :

- ouvrir un PDF born-digital
- extraire une IR structuree avec PyMuPDF
- proteger certains segments sensibles avant traduction
- traduire via LM Studio local
- restaurer les placeholders
- ecrire le resultat dans `data/debug/document_ir.json`

La v1 ne fait pas encore :

- la recomposition PDF finale
- l'overlay in-place
- la gestion avancee des tableaux complexes
- la gestion fine des formules scientifiques
- la QA visuelle finale

## Structure du projet

```text
pdf-translator/
├── .env
├── .env.example
├── data/
│   ├── input/
│   ├── output/
│   └── debug/
├── scripts/
├── src/pdf_translator/
└── tests/
```

## Environnement local de reference

- Python: `3.9.6`
- venv: `.venv`
- backend local: LM Studio
- modele local teste: `translategemma-4b-it`
- endpoint local: `http://localhost:4000/v1`

## Installation

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Variables principales dans `.env` :

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
```

## Reglages stables recommandes sur cette machine

Pour le Mac local actuel, le profil le plus stable observe est :

- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES=1`
- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS=160`
- `PDF_TRANSLATOR_BATCH_MAX_SEGMENTS=2`
- `PDF_TRANSLATOR_BATCH_MAX_CHARS=800`
- `PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS=45`

Avec ces reglages, `scientifique-mixte.pdf` a ete traite avec succes en `11` batchs.

## Mode contextuel experimental

Le code supporte deja un regroupement contextuel multi-lignes dans `src/pdf_translator/translate/batching.py`.

But :

- donner plus de contexte au modele
- ameliorer la qualite sur les phrases coupees sur plusieurs lignes

Etat actuel :

- prometteur sur le fond
- encore trop fragile avec `translategemma-4b-it` sur cette machine
- conserve dans le code, mais desactive par defaut via la config

Pour le reactiver plus tard sur une machine plus puissante, augmenter par exemple :

- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES`
- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS`

et revalider le comportement du modele.

## Utilisation

Commande principale :

```bash
./.venv/bin/python -m pdf_translator.cli data/input/monfichier.pdf
```

ou, si le package est bien installe dans le venv :

```bash
pdf-translator data/input/monfichier.pdf
```

Le resultat intermediaire est ecrit dans :

```text
data/debug/document_ir.json
```

## Tests

Commande recommandee :

```bash
./.venv/bin/python -m pytest
```

## Jeux de test utiles

Dans `data/input/` :

- `docnavettepourtestsimple.pdf` : premier PDF simple historique
- `simple-fr.pdf` : texte francais continu avec placeholders
- `scientifique-mixte.pdf` : cas le plus representatif actuellement
- `layout-tricky.pdf` : mise en page plus delicate

Regeneration des PDF synthetiques :

```bash
./.venv/bin/python scripts/generate_test_pdfs.py
```

## Placeholders proteges actuellement

Protections deja implementees :

- emails
- URLs
- commits / hashes longs
- dates ISO
- versions logicielles de type `x.y.z`

## Comportement de securite de la v1

Le pipeline est maintenant defensif :

- validation stricte des IDs de sortie
- validation des placeholders preserves
- tolerance a certains preambules parasites du modele comme `### Response:`
- fallback si un batch echoue
- preservation directe du `protected_text` si le backend timeout

L'objectif ici est de privilegier une v1 locale stable et transferable.

## Checklist de transfert vers une machine plus puissante

Quand le projet sera deplace vers un environnement plus fort :

1. recreer un venv propre
2. installer le package avec `pip install -e .`
3. recopier `.env` puis ajuster le backend et le modele
4. verifier `python -m pytest`
5. tester `simple-fr.pdf`
6. tester `scientifique-mixte.pdf`
7. seulement apres, augmenter progressivement :
   - `PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS`
   - `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES`
   - `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS`
   - `PDF_TRANSLATOR_BATCH_MAX_SEGMENTS`
   - `PDF_TRANSLATOR_BATCH_MAX_CHARS`

## Prochaine etape recommandee

La prochaine grande etape produit est :

1. garder cette v1 stable comme base
2. transferer sur une machine plus puissante
3. reessayer le mode contextuel multi-lignes
4. ensuite attaquer la couche overlay / recomposition PDF
