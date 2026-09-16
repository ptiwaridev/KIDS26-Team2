"""Loads the structured MIMIC-IV subset into Azure SQL, filtered down to the
configured cohorts (config/cohorts.json): the original 7 core hosp/ tables
(patients, admissions, diagnoses_icd, labevents, prescriptions + 2
dictionaries) plus tables added for epidemiology/health-services research —
microbiologyevents, procedures_icd (+dictionary), drgcodes, services, omr
(all hosp/), and icustays, chartevents, inputevents, outputevents, d_items
(all icu/ — bedside vitals, IV fluids/vasopressors, urine output; needed for
severity scoring and sepsis fluid-resuscitation research that labs/meds
alone can't support).

Source data can be either:
  - a local directory of real MIMIC-IV hosp CSVs (.csv or .csv.gz — real data
    is credentialed-access-only) — pass --icu-source too if icu/ isn't a
    sibling directory of --source, for the icu/ tables, or
  - the output of generate_synthetic_data.py (only the original 7 tables;
    newer tables are skipped with a warning since the generator doesn't
    produce them yet), or
  - an s3:// prefix (for credentialed members pulling from PhysioNet's AWS
    Open Data mirror) — requires AWS credentials with access to that bucket.

Real MIMIC-IV files carry extra columns beyond our subset schema (e.g.
admissions has admit_provider_id/edregtime/edouttime) — those are dropped via
usecols. labevents, prescriptions, and chartevents are also too large to load
into memory whole (chartevents.csv.gz alone is 433M rows), so they're
streamed in chunks and filtered to the cohort's hadm_ids before ever being
fully materialized — this relies on those files being sorted ascending by
subject_id (verified for MIMIC-IV v3.1) so scanning can stop once a chunk is
entirely past the cohort's highest subject_id.

Usage:
    python scripts/ingest_structured.py --source data/synthetic
    python scripts/ingest_structured.py --source /path/to/mimic-iv-3.1/hosp
    python scripts/ingest_structured.py --source s3://physionet-mimic-iv/hosp

Assumes sql/schema.sql has already been applied to the target database.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from cohort_utils import all_cohort_prefixes
from db import get_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COHORT_IDS_PATH = PROJECT_ROOT / "data" / "cohort_subject_ids.txt"

# Reference/dictionary tables — loaded in full, never filtered to the cohort.
REFERENCE_TABLES = {
    "d_icd_diagnoses": ["icd_code", "icd_version", "long_title"],
    "d_labitems": ["itemid", "label", "fluid", "category"],
    "d_icd_procedures": ["icd_code", "icd_version", "long_title"],
    "d_items": ["itemid", "label", "abbreviation", "category", "unitname", "param_type"],
}

# Tables small enough to load in full then filter down to the cohort in
# memory (as opposed to LARGE_TABLES below, which must be streamed).
# filter_col is which column to filter by: "subject_id" for tables where
# hadm_id can legitimately be NULL (pre-admission/outpatient events, e.g. an
# ED blood culture drawn before formal admission) — filtering those by
# hadm_id would silently drop real cohort data. Tables where hadm_id is
# always present filter by hadm_id directly.
CORE_TABLES = {
    "patients": (["subject_id", "gender", "anchor_age", "anchor_year", "anchor_year_group", "dod"],
                 "subject_id"),
    "admissions": (["hadm_id", "subject_id", "admittime", "dischtime", "deathtime", "admission_type",
                     "admission_location", "discharge_location", "insurance", "language",
                     "marital_status", "race", "hospital_expire_flag"], "subject_id"),
    "diagnoses_icd": (["subject_id", "hadm_id", "seq_num", "icd_code", "icd_version"], "hadm_id"),
    "microbiologyevents": (["microevent_id", "subject_id", "hadm_id", "chartdate", "charttime",
                             "spec_type_desc", "test_name", "org_name", "ab_name", "interpretation"],
                            "subject_id"),
    "procedures_icd": (["subject_id", "hadm_id", "seq_num", "chartdate", "icd_code", "icd_version"],
                        "hadm_id"),
    "drgcodes": (["subject_id", "hadm_id", "drg_type", "drg_code", "description",
                  "drg_severity", "drg_mortality"], "hadm_id"),
    "services": (["subject_id", "hadm_id", "transfertime", "prev_service", "curr_service"], "hadm_id"),
    "omr": (["subject_id", "chartdate", "seq_num", "result_name", "result_value"], "subject_id"),
    "icustays": (["subject_id", "hadm_id", "stay_id", "first_careunit", "last_careunit",
                  "intime", "outtime", "los"], "hadm_id"),
    "inputevents": (["subject_id", "hadm_id", "stay_id", "itemid", "starttime", "endtime",
                      "amount", "amountuom", "rate", "rateuom", "ordercategorydescription"], "hadm_id"),
    "outputevents": (["subject_id", "hadm_id", "stay_id", "itemid", "charttime", "value", "valueuom"],
                      "hadm_id"),
}
# Columns that are genuinely integer-typed in the schema but read as float64
# by pandas because the source column has NaNs (e.g. hadm_id null for
# pre-admission events) — cast to pandas' nullable Int64 so real values
# insert as ints, not floats, and NaN maps cleanly to SQL NULL.
NULLABLE_INT_COLUMNS = {
    "microbiologyevents": ["hadm_id"],
    "drgcodes": ["drg_severity", "drg_mortality"],
}
# Columns typed DATE in the schema but stored as full timestamp strings
# ("YYYY-MM-DD 00:00:00") in some real MIMIC-IV files — truncate to the date
# portion or the ODBC driver rejects the extra length against a DATE column.
DATE_ONLY_COLUMNS = {
    "microbiologyevents": ["chartdate"],
}

LARGE_TABLES = {
    "labevents": ["labevent_id", "subject_id", "hadm_id", "itemid", "charttime",
                  "valuenum", "valueuom", "flag"],
    "prescriptions": ["pharmacy_id", "subject_id", "hadm_id", "starttime", "stoptime",
                       "drug", "dose_val_rx", "dose_unit_rx", "route"],
    # chartevents is the biggest file in MIMIC-IV (433M rows) — needs the same
    # streamed + early-stop treatment as labevents, not a plain in-memory read.
    "chartevents": ["subject_id", "hadm_id", "stay_id", "itemid", "charttime", "valuenum", "valueuom"],
}
LARGE_FILE_CHUNK_ROWS = 500_000

# Load order matters for FK constraints: dictionaries and parents before children.
# icustays must precede inputevents/outputevents (and chartevents, loaded
# separately below) since they FK-reference icustays(stay_id).
LOAD_ORDER = ["d_icd_diagnoses", "d_labitems", "d_icd_procedures", "d_items",
              "patients", "admissions",
              "diagnoses_icd", "procedures_icd", "microbiologyevents",
              "drgcodes", "services", "omr", "icustays",
              "inputevents", "outputevents"]

# These live in MIMIC-IV's icu/ folder, not hosp/ — everything else in
# REFERENCE_TABLES/CORE_TABLES/LARGE_TABLES is a hosp/ file.
ICU_TABLES = {"icustays", "d_items", "inputevents", "outputevents", "chartevents"}


def resolve_path(source: str, table: str) -> str:
    base = f"{source.rstrip('/')}/{table}"
    if source.startswith("s3://"):
        return f"{base}.csv"  # PhysioNet's s3 mirror serves plain .csv
    for ext in (".csv", ".csv.gz"):
        candidate = Path(base + ext)
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(f"Could not find {table}.csv or {table}.csv.gz under {source}")


def read_table(source: str, table: str, cols: list[str]) -> pd.DataFrame:
    path = resolve_path(source, table)
    return pd.read_csv(path, usecols=cols)


def select_cohort_hadm_ids(diagnoses: pd.DataFrame, max_total_patients: int) -> tuple[set, set]:
    prefixes = all_cohort_prefixes()
    codes = diagnoses["icd_code"].astype(str).str.replace(".", "", regex=False).str.upper()
    icd10_prefixes = tuple(p.upper() for p in prefixes["icd10_prefixes"])
    icd9_prefixes = tuple(p.upper() for p in prefixes["icd9_prefixes"])
    is_icd10 = diagnoses["icd_version"] == 10

    mask = pd.Series(False, index=diagnoses.index)
    if icd10_prefixes:
        mask |= is_icd10 & codes.str.startswith(icd10_prefixes)
    if icd9_prefixes:
        mask |= ~is_icd10 & codes.str.startswith(icd9_prefixes)
    cohort_diagnoses = diagnoses[mask]
    hadm_ids = set(cohort_diagnoses["hadm_id"].unique())
    subject_ids = set(cohort_diagnoses["subject_id"].unique())

    if len(subject_ids) > max_total_patients:
        keep_subjects = set(sorted(subject_ids)[:max_total_patients])
        subject_ids = keep_subjects
        hadm_ids = set(cohort_diagnoses[cohort_diagnoses["subject_id"].isin(keep_subjects)]["hadm_id"].unique())

    return subject_ids, hadm_ids


def stream_filtered_chunks(path: str, usecols: list[str], hadm_ids: set, chunk_rows: int,
                            max_subject_id: int | None = None):
    """Reads a (possibly huge, possibly gzipped) CSV in chunks and yields only
    the rows whose hadm_id is in the cohort — bounds memory regardless of the
    source file's total size.

    Real MIMIC-IV hosp CSVs (verified for labevents.csv.gz and
    prescriptions.csv.gz in v3.1) are sorted ascending by subject_id.
    select_cohort_hadm_ids() deliberately caps the cohort to its numerically
    smallest matching subject_ids, so once a chunk's subject_ids are all past
    max_subject_id, no later row can match either — we can stop scanning
    instead of reading the remaining tens of millions of rows for nothing.
    This is what makes loading labevents.csv.gz (158M rows) tractable.
    """
    for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_rows):
        if max_subject_id is not None and chunk["subject_id"].min() > max_subject_id:
            break
        chunk = chunk.dropna(subset=["hadm_id"])
        chunk["hadm_id"] = chunk["hadm_id"].astype("int64")
        filtered = chunk[chunk["hadm_id"].isin(hadm_ids)]
        if not filtered.empty:
            yield filtered


def load_dataframe(df: pd.DataFrame, table: str, engine, sql_batch_size: int):
    # No method="multi" — that builds one multi-row INSERT and hits SQL
    # Server's 2100-parameter-per-statement limit on wide/large batches.
    # fast_executemany=True on the engine already makes plain executemany fast
    # via array binding, so let pandas hand it large batches directly instead
    # of us re-slicing into many separate to_sql calls (each one a network
    # round-trip) — that re-slicing was the actual bottleneck, not the DB.
    df.to_sql(table, engine, if_exists="append", index=False, chunksize=sql_batch_size)


def load_large_table(source_dir: str, table: str, hadm_ids: set, max_subject_id: int, engine, sql_batch_size: int):
    path = resolve_path(source_dir, table)
    total_rows = 0
    print(f"Streaming {table} from {path} ...")
    for filtered_chunk in tqdm(stream_filtered_chunks(path, LARGE_TABLES[table], hadm_ids, LARGE_FILE_CHUNK_ROWS,
                                                        max_subject_id=max_subject_id),
                                desc=table, unit="chunk"):
        load_dataframe(filtered_chunk, table, engine, sql_batch_size)
        total_rows += len(filtered_chunk)
    print(f"  {table}: {total_rows} rows matched cohort and were loaded")


def source_dir_for(table: str, source: str, icu_source: str | None) -> str:
    if table in ICU_TABLES:
        if icu_source:
            return icu_source
        # Convenience default for the common MIMIC-IV layout: .../mimic-iv-3.1/hosp
        # and .../mimic-iv-3.1/icu as siblings.
        guessed = str(Path(source).parent / "icu")
        return guessed
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True,
                         help="Local dir (MIMIC-IV hosp/ or generate_synthetic_data.py output) or s3:// prefix")
    parser.add_argument("--icu-source", default=None,
                         help="Local dir for MIMIC-IV icu/ files (for icustays). "
                              "Defaults to a sibling 'icu' folder next to --source.")
    parser.add_argument("--max-patients", type=int, default=2000)
    parser.add_argument("--sql-batch-size", type=int, default=50_000,
                         help="Rows per fast_executemany batch (higher = fewer network round-trips)")
    args = parser.parse_args()

    # Not every table exists for every source — the synthetic generator only
    # produces the original 7 tables, so newer tables are skipped (with a
    # warning) rather than failing the whole run.
    missing = set()

    def try_read(table, cols, base_source):
        try:
            return read_table(base_source, table, cols)
        except FileNotFoundError:
            print(f"  skipping {table}: not found under {base_source} (fine for older synthetic data)")
            missing.add(table)
            return None

    print(f"Reading reference dictionaries from {args.source} ...")
    reference_dfs = {}
    for table, cols in REFERENCE_TABLES.items():
        df = try_read(table, cols, source_dir_for(table, args.source, args.icu_source))
        if df is not None:
            reference_dfs[table] = df

    print(f"Reading core cohort-filterable tables from {args.source} ...")
    core_dfs = {}
    for table, (cols, _) in CORE_TABLES.items():
        df = try_read(table, cols, source_dir_for(table, args.source, args.icu_source))
        if df is not None:
            core_dfs[table] = df

    print("Selecting cohort subset by ICD prefixes (config/cohorts.json) ...")
    subject_ids, hadm_ids = select_cohort_hadm_ids(core_dfs["diagnoses_icd"], args.max_patients)
    print(f"  {len(subject_ids)} patients / {len(hadm_ids)} admissions in cohort")

    for table, (_, filter_col) in CORE_TABLES.items():
        if table not in core_dfs:
            continue
        df = core_dfs[table]
        if filter_col == "subject_id":
            df = df[df["subject_id"].isin(subject_ids)].copy()
        else:
            df = df[df["hadm_id"].isin(hadm_ids)].copy()
        for int_col in NULLABLE_INT_COLUMNS.get(table, []):
            df[int_col] = df[int_col].astype("Int64")
        for date_col in DATE_ONLY_COLUMNS.get(table, []):
            df[date_col] = df[date_col].astype(str).str[:10]
        core_dfs[table] = df

    COHORT_IDS_PATH.parent.mkdir(exist_ok=True)
    COHORT_IDS_PATH.write_text("\n".join(str(s) for s in sorted(subject_ids)))

    engine = get_engine()
    all_dfs = {**reference_dfs, **core_dfs}
    for table in LOAD_ORDER:
        if table in missing:
            continue
        df = all_dfs[table]
        print(f"Loading {table}: {len(df)} rows ...")
        load_dataframe(df, table, engine, args.sql_batch_size)

    max_subject_id = max(subject_ids)
    for table in LARGE_TABLES:
        source_dir = source_dir_for(table, args.source, args.icu_source)
        try:
            resolve_path(source_dir, table)
        except FileNotFoundError:
            print(f"  skipping {table}: not found under {source_dir} (fine for older synthetic data)")
            continue
        load_large_table(source_dir, table, hadm_ids, max_subject_id, engine, args.sql_batch_size)

    print("Done.")


if __name__ == "__main__":
    main()
