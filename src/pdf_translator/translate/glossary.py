from __future__ import annotations

import re


SLIDE_TITLE_PHRASES = (
    ("EN DYNAMIQUE", "UNDER DYNAMIC CONDITIONS"),
    ("À L’EQUILIBRE THERMODYNAMIQUE", "AT THERMODYNAMIC EQUILIBRIUM"),
    ("A L’EQUILIBRE THERMODYNAMIQUE", "AT THERMODYNAMIC EQUILIBRIUM"),
    ("A L'EQUILIBRE THERMODYNAMIQUE", "AT THERMODYNAMIC EQUILIBRIUM"),
    ("ÉQUILIBRE THERMODYNAMIQUE", "THERMODYNAMIC EQUILIBRIUM"),
)

SLIDE_TITLE_TOKENS = {
    "JONCTION": "JUNCTION",
    "CONNEXION": "CONNECTION",
    "JONCTIONS": "JUNCTIONS",
    "THERMODYNAMIQUE": "THERMODYNAMIC",
    "EQUILIBRE": "EQUILIBRIUM",
    "ÉQUILIBRE": "EQUILIBRIUM",
    "PRINCIPE": "PRINCIPLE",
    "FONCTIONNEMENT": "OPERATION",
    "CELLULE": "CELL",
    "PHOTOVOLTAIQUE": "PHOTOVOLTAIC",
    "PHOTOVOLTAÏQUE": "PHOTOVOLTAIC",
    "DIODE": "DIODE",
    "DIODES": "DIODES",
    "INTRODUCTION": "INTRODUCTION",
    "CONCLUSION": "CONCLUSION",
    "COMPARAISON": "COMPARISON",
    "CHAPITRE": "CHAPTER",
    "LES": "THE",
    "DE": "OF",
    "DU": "OF THE",
    "DES": "OF THE",
    "LA": "THE",
    "LE": "THE",
    "ET": "AND",
    "A": "AT",
    "À": "AT",
}


OUTLINE_SENTENCE_TRANSLATIONS = {
    "Nous avons décrits phénoménologiquement ce qui se passe, étape par étape:": (
        "We have described phenomenologically what happens, step by step:"
    ),
    "2. La conséquence de l’établissement d’une ZCE négative côté P, positive côté N :": (
        "2. The consequence of the establishment of a negative SCR on the P side and a positive SCR on the N side:"
    ),
    "Commençons par une polarisation en direct, pour cela c’est facile :\nOn relie la région P du matériau SC au pole + d’un générateur de tension et": (
        "Let us begin with forward biasing; it is simple:\nThe P region of the semiconductor is connected to the + terminal of a voltage source and"
    ),
    "la région N au pôle – de ce générateur de tension.\nC’est facile de s’en souvenir, P comme positif et N comme négatif.": (
        "the N region to the - terminal of this voltage source.\nIt is easy to remember: P for positive and N for negative."
    ),
    "Commençons par une polarisation en direct, pour cela c’est facile :": (
        "Let us begin with forward biasing; it is quite straightforward:"
    ),
    "On relie la région P du matériau SC au pole + d’un générateur de tension et": (
        "The P region of the semiconductor is connected to the positive terminal of a voltage source and"
    ),
    "la région N au pôle – de ce générateur de tension.": (
        "the N region to the negative terminal of this voltage source."
    ),
    "C’est facile de s’en souvenir, P comme positif et N comme négatif.": (
        "It is easy to remember: P for positive and N for negative."
    ),
    "1 - La Conductance de la jonction": "1 - Junction conductance",
    "Nous aborderons donc le calcul de :": "We will therefore examine the calculation of:",
    "2 - La Capacité de Stockage et de Transition": "2 - Storage and transition capacitance",
}


SCIENTIFIC_LABEL_TRANSLATIONS = {
    "CONTACT OHMIQUE": "OHMIC CONTACT",
    "Contact ohmique": "Ohmic contact",
    "contact ohmique": "ohmic contact",
    "SEMICONDUCTEUR": "SEMICONDUCTOR",
    "Semiconducteur": "Semiconductor",
    "semiconducteur": "semiconductor",
    "HOMOJONCTION": "HOMOJUNCTION",
    "Homojonction": "Homojunction",
    "homojonction": "homojunction",
    "ISOTYPE": "ISOTYPE",
    "Isotype": "Isotype",
    "isotype": "isotype",
    "ANISOTYPE": "ANISOTYPE",
    "Anisotype": "Anisotype",
    "anisotype": "anisotype",
    "Si type P": "P-type Si",
    "Si type N": "N-type Si",
    "Si type P+": "P+-type Si",
    "Si type N+": "N+-type Si",
    "si type p": "p-type Si",
    "si type n": "n-type Si",
    "JONCTION P/N": "P/N JUNCTION",
    "Jonction P/N": "P/N junction",
    "jonction p/n": "p/n junction",
    "Jonction PN": "PN junction",
    "jonction pn": "pn junction",
    "ZONE DE TRANSITION": "DEPLETION REGION",
    "Zone de transition": "Depletion region",
    "zone de transition": "depletion region",
    "BARRIÈRE DE POTENTIEL": "POTENTIAL BARRIER",
    "BARRIERE DE POTENTIEL": "POTENTIAL BARRIER",
    "Barrière de potentiel": "Potential barrier",
    "barrière de potentiel": "potential barrier",
    "ZONE DE CHARGE D’ESPACE": "SPACE-CHARGE REGION",
    "ZONE DE CHARGE D'ESPACE": "SPACE-CHARGE REGION",
    "Zone de charge d’espace": "Space-charge region",
    "Zone de charge d'espace": "Space-charge region",
    "zone de charge d’espace": "space-charge region",
    "zone de charge d'espace": "space-charge region",
    "COURANT DE DIFFUSION DES MINORITAIRES": "MINORITY-CARRIER DIFFUSION CURRENT",
    "Courant de diffusion des minoritaires": "Minority-carrier diffusion current",
    "courant de diffusion des minoritaires": "minority-carrier diffusion current",
    "COURANT DE GENERATION THERMIQUE": "THERMAL GENERATION CURRENT",
    "Courant de generation thermique": "Thermal generation current",
    "courant de generation thermique": "thermal generation current",
    "BILAN DES COURANTS DE FUITE": "LEAKAGE CURRENT BALANCE",
    "Bilan des courants de fuite": "Leakage current balance",
    "bilan des courants de fuite": "leakage current balance",
    "CAPACITE DE STOCKAGE": "STORAGE CAPACITANCE",
    "Capacite de stockage": "Storage capacitance",
    "capacite de stockage": "storage capacitance",
    "CAPACITE DE TRANSITION": "TRANSITION CAPACITANCE",
    "Capacite de transition": "Transition capacitance",
    "capacite de transition": "transition capacitance",
    "TENSION D’AVALANCHE": "BREAKDOWN VOLTAGE",
    "TENSION D'AVALANCHE": "BREAKDOWN VOLTAGE",
    "Tension d’avalanche": "Breakdown voltage",
    "Tension d'avalanche": "Breakdown voltage",
    "tension d’avalanche": "breakdown voltage",
    "tension d'avalanche": "breakdown voltage",
}


def translate_slide_title(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    translated = normalized
    for source, target in SLIDE_TITLE_PHRASES:
        translated = translated.replace(source, target)

    parts = re.split(r"(\W+)", translated)
    converted: list[str] = []

    for part in parts:
        replacement = SLIDE_TITLE_TOKENS.get(part)
        converted.append(replacement if replacement is not None else part)

    translated = "".join(converted)
    translated = re.sub(r"\s+", " ", translated).strip()
    return translated


def translate_outline_sentence(text: str) -> str | None:
    normalized = text.strip()
    return OUTLINE_SENTENCE_TRANSLATIONS.get(normalized)


def translate_scientific_label(text: str) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    return SCIENTIFIC_LABEL_TRANSLATIONS.get(normalized)
