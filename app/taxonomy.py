"""Subject normalisation used by the guard. Maps many names for one concept to a canonical subject.
Anything not listed here falls back to embedding similarity between subject names (see guard.py)."""
import re

ALIASES: dict[str, list[str]] = {
    "fox": ["foxes", "vixen", "red fox", "vulpes vulpes", "vulpes", "fox kit", "fox cub", "wild fox", "arctic fox"],
    "wolf": ["gray wolf", "grey wolf", "canis lupus", "timber wolf", "wolves"],
    "dog": ["domestic dog", "puppy", "canis familiaris", "labrador", "retriever", "husky", "shepherd dog", "dogs"],
    "bear": ["brown bear", "grizzly", "grizzly bear", "black bear", "ursus arctos", "polar bear", "bears"],
    "deer": ["stags", "fawns", "white-tailed deer", "red deer", "fawn", "stag", "doe", "roe deer", "cervus", "elk"],
}
_INDEX = sorted(((alias, canon) for canon, al in ALIASES.items() for alias in [canon, *al]),
                key=lambda x: -len(x[0]))


def canonical(subject: str | None) -> str | None:
    """'Vulpes vulpes' -> 'fox'; 'gray wolf' -> 'wolf'; unknown -> the cleaned subject itself."""
    if not subject:
        return None
    s = re.sub(r"[^a-z\s-]", " ", subject.lower()).strip()
    for alias, canon in _INDEX:
        if re.search(rf"\b{re.escape(alias)}\b", s):
            return canon
    return s or None


def known_subject(text: str) -> str | None:
    """Return a canonical subject only if an alias actually appears in the text."""
    t = text.lower()
    for alias, canon in _INDEX:
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return canon
    return None


def expand_synonyms(text: str) -> str:
    """Append canonical names to text (used only by the offline mock embedder)."""
    extra = [canon for alias, canon in _INDEX if re.search(rf"\b{re.escape(alias)}\b", text.lower())]
    return text + " " + " ".join(extra)
