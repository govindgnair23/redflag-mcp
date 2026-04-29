from __future__ import annotations

from pathlib import Path

import yaml

LEXICON_PATH = Path(__file__).resolve().parent.parent / "data/lexicon/aliases.yaml"

REQUIRED_TERMS = {
    "tbml", "cvc", "msb", "ctr", "sar", "bsa",
    "npo", "pep", "sfpf", "kyc", "cdd", "edd",
    "fatf", "dnfbp", "hawala", "smurfing",
}


def _load_aliases() -> dict:
    return yaml.safe_load(LEXICON_PATH.read_text())


def test_aliases_yaml_exists():
    assert LEXICON_PATH.exists(), f"aliases.yaml not found at {LEXICON_PATH}"


def test_aliases_loads_as_dict():
    aliases = _load_aliases()
    assert isinstance(aliases, dict), "aliases.yaml must be a top-level mapping"


def test_all_values_are_lists_of_strings():
    aliases = _load_aliases()
    for key, expansions in aliases.items():
        assert isinstance(expansions, list), f"Value for '{key}' must be a list"
        for exp in expansions:
            assert isinstance(exp, str), f"Expansion '{exp}' for '{key}' must be a string"


def test_all_required_terms_present():
    aliases = _load_aliases()
    missing = REQUIRED_TERMS - set(aliases.keys())
    assert not missing, f"Required alias terms missing from lexicon: {sorted(missing)}"


def test_all_expansion_lists_are_non_empty():
    aliases = _load_aliases()
    empty = [key for key, expansions in aliases.items() if not expansions]
    assert not empty, f"Alias entries with empty expansion lists: {empty}"


def test_all_keys_are_lowercase():
    aliases = _load_aliases()
    non_lower = [key for key in aliases if key != key.lower()]
    assert not non_lower, f"Alias keys must be lowercase: {non_lower}"


def test_no_empty_expansion_strings():
    aliases = _load_aliases()
    offenders = [
        (key, exp)
        for key, expansions in aliases.items()
        for exp in expansions
        if not exp or not exp.strip()
    ]
    assert not offenders, f"Empty expansion strings found: {offenders}"
