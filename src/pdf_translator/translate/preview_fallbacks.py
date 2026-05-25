from __future__ import annotations

import re
import unicodedata


STEP_LABEL_RE = re.compile(r"^etape\s+(\d+)$")
SERVINGS_LABEL_RE = re.compile(r"^pour\s+(\d+)\s+personnes?$")
QUANTITY_WITH_UNIT_RE = re.compile(r"^(\d+(?:[,.]\d+)?)\s*([a-z ]+?)\s+(?:de|d')\s*(.+)$")
QUANTITY_DIRECT_RE = re.compile(r"^(\d+(?:[,.]\d+)?)\s+(.+)$")

STRUCTURAL_LABEL_TRANSLATIONS = {
    "ingredients": "Ingredients",
}

SIMPLE_UNIT_TRANSLATIONS = {
    "g": "g",
    "kg": "kg",
    "mg": "mg",
    "ml": "ml",
    "cl": "cl",
    "l": "l",
    "tasse": "cup",
    "tasses": "cups",
    "sachet": "packet",
    "sachets": "packets",
    "cuillere a cafe": "tsp",
    "cuilleres a cafe": "tsp",
    "cuillere a soupe": "tbsp",
    "cuilleres a soupe": "tbsp",
}

SIMPLE_INGREDIENT_TRANSLATIONS = {
    "oeuf": "egg",
    "oeufs": "eggs",
    "sucre": "sugar",
    "sucre roux": "brown sugar",
    "mascarpone": "mascarpone",
    "biscuits": "biscuits",
    "biscuits a la cuillere": "ladyfingers",
    "cafe": "coffee",
    "cafe fort": "strong coffee",
    "sucre vanille": "vanilla sugar",
    "cacao": "cocoa",
    "cacao amer": "unsweetened cocoa",
}


def _normalized_structural_key(text: str) -> str:
    folded = text.strip().replace("’", "'").replace("œ", "oe").replace("Œ", "oe")
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = folded.lower()
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def _translate_simple_quantity(key: str) -> str | None:
    match = QUANTITY_WITH_UNIT_RE.fullmatch(key)
    if match is not None:
        amount, unit_source, item_source = match.groups()
        unit = SIMPLE_UNIT_TRANSLATIONS.get(unit_source.strip())
        item = SIMPLE_INGREDIENT_TRANSLATIONS.get(item_source.strip())
        if unit is not None and item is not None:
            return f"{amount} {unit} {item}"

    match = QUANTITY_DIRECT_RE.fullmatch(key)
    if match is not None:
        amount, item_source = match.groups()
        item = SIMPLE_INGREDIENT_TRANSLATIONS.get(item_source.strip())
        if item is not None:
            return f"{amount} {item}"

    return None


def _translate_single_structural_text(text: str) -> str | None:
    key = _normalized_structural_key(text)
    if not key:
        return None

    step_match = STEP_LABEL_RE.fullmatch(key)
    if step_match is not None:
        return f"step {step_match.group(1)}"

    servings_match = SERVINGS_LABEL_RE.fullmatch(key)
    if servings_match is not None:
        return f"For {servings_match.group(1)} people"

    label_translation = STRUCTURAL_LABEL_TRANSLATIONS.get(key)
    if label_translation is not None:
        return label_translation

    return _translate_simple_quantity(key)


def translate_structural_text(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) == 1:
        return _translate_single_structural_text(lines[0])

    translated_lines: list[str] = []
    for line in lines:
        translated_line = _translate_single_structural_text(line)
        if translated_line is None:
            return None
        translated_lines.append(translated_line)
    return "\n".join(translated_lines)
