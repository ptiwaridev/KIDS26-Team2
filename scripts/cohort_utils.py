"""Shared cohort/ICD-prefix resolution for ingestion scripts and (later) the
Text-to-SQL agent. Reads config/clinical_terms.json and config/cohorts.json
so the term->code mapping is defined in exactly one place.
"""
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_json(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return json.load(f)


def cohort_icd_prefixes(cohort_key: str) -> dict:
    """Return {'icd10_prefixes': [...], 'icd9_prefixes': [...]} for a cohort,
    unioning the prefixes of every clinical term listed under it."""
    cohorts = load_json("cohorts.json")
    terms = load_json("clinical_terms.json")

    if cohort_key not in cohorts:
        raise KeyError(f"Unknown cohort '{cohort_key}' — see config/cohorts.json")

    icd10, icd9 = set(), set()
    for term in cohorts[cohort_key]["terms"]:
        icd10.update(terms[term].get("icd10_prefixes", []))
        icd9.update(terms[term].get("icd9_prefixes", []))
    return {"icd10_prefixes": sorted(icd10), "icd9_prefixes": sorted(icd9)}


def all_cohort_prefixes() -> dict:
    """Same as cohort_icd_prefixes but unioned across every configured cohort —
    used when carving the overall subset (all cohorts together)."""
    cohorts = load_json("cohorts.json")
    icd10, icd9 = set(), set()
    for key in cohorts:
        if key.startswith("_"):
            continue
        prefixes = cohort_icd_prefixes(key)
        icd10.update(prefixes["icd10_prefixes"])
        icd9.update(prefixes["icd9_prefixes"])
    return {"icd10_prefixes": sorted(icd10), "icd9_prefixes": sorted(icd9)}


def code_matches(icd_code: str, icd_version: int, prefixes: dict) -> bool:
    code = icd_code.replace(".", "").upper()
    candidates = prefixes["icd10_prefixes"] if icd_version == 10 else prefixes["icd9_prefixes"]
    return any(code.startswith(p.upper()) for p in candidates)
