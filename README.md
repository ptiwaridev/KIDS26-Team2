# Clinical Data Assistant

A conversational interface that lets researchers query clinical data in
natural language, combining Text-to-SQL (structured data) with RAG
(unstructured clinical notes), routed by a lightweight agent layer.

Built on a MIMIC-IV subset (~1,500 patients, sepsis + heart failure cohorts).

## Access — read this before doing anything else

Real MIMIC-IV / MIMIC-IV-Note data is loaded into our Azure SQL and Azure AI
Search instances, and it may only be accessed by **PhysioNet-credentialed
team members** — at every stage, including through this app, not just the
raw files. This applies to more than the cloud resources: `data/cohort_notes.csv`
(generated locally by ingestion) contains real, unredacted note text and is
gitignored for exactly this reason — never share it outside the credentialed
group either.

Repo/code access is fine for the whole team — nothing in this codebase is
patient data. Only the `.env` values (Azure connection info) are restricted,
and only credentialed members should receive them.

## Setup

See [SETUP.md](SETUP.md) for getting a dev environment running (devcontainer,
Docker Compose, or local venv), provisioning Azure resources, and loading
data. Short version:

```
cp .env.example .env   # fill in values — ask a credentialed teammate
make docker-up
```

## Architecture

- **Structured data** (Azure SQL): discrete/coded fields — labs, meds,
  diagnoses, ICU stays. Queried via Text-to-SQL with the schema described
  directly in the prompt (small enough not to need a retrieval layer).
- **Unstructured data** (Azure AI Search): discharge summaries and radiology
  reports, chunked and embedded (`text-embedding-3-small` via Azure AI
  Foundry), retrieved with hybrid keyword + vector search.
- **Agent layer**: routes a question to SQL, RAG, or both, and can chain them
  — e.g. SQL finds a patient cohort, then notes retrieval filters to those
  patient IDs via Azure AI Search's `subject_id`/`hadm_id` filterable fields.
- **Generation**: Claude Sonnet 5, Azure-hosted via Azure AI Foundry.

## Data scope

The subset covers 18 tables total (see [sql/schema.sql](sql/schema.sql) for
exact columns), but not all of them are in scope for the agent build given
the time budget. **See [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for a plain-English
walkthrough of every in-scope table and column** — what each one means, not
just its type. Short version:

**Build around these** (patients, admissions, diagnoses_icd + dictionary,
labevents + dictionary, prescriptions, microbiologyevents, icustays) plus
**discharge summaries** in Azure AI Search. All column-keyed, straightforward
joins, no lookup layer required beyond the ICD synonym table.

**Loaded but out of scope for now** (procedures_icd + dictionary, drgcodes,
services, omr, chartevents, inputevents, outputevents, d_items) — costs
nothing sitting unused; the reason to leave them out of the agent's prompt is
that `chartevents`/`inputevents`/`outputevents` are itemid-keyed (see
[config/icu_item_lookup.json](config/icu_item_lookup.json)) and need real
engineering time to be reliably queryable — a stretch goal, not a dependency.
Radiology reports are the same call for the notes side: add them only if
discharge-summary RAG is solid and time remains.

Two config files exist so the agent doesn't have to guess at query time:
- [config/clinical_terms.json](config/clinical_terms.json) — clinical term →
  ICD code prefixes (e.g. "sepsis" → its codes).
- [config/icu_item_lookup.json](config/icu_item_lookup.json) — verified
  itemid for each vital/fluid that matters, for when/if the ICU tables get
  built against.

## Repo layout

```
README.md                This file
DATA_DICTIONARY.md       What every in-scope table/column means
SETUP.md                 Dev environment + Azure provisioning + data loading
app.py                  Streamlit entrypoint (skeleton — agent not wired up yet)
sql/schema.sql           Full 18-table schema
scripts/
  provision_azure.sh      Az CLI provisioning (resource group, SQL, Search, Foundry)
  generate_synthetic_data.py  Synthetic data matching the real schema
  ingest_structured.py    Loads MIMIC-IV hosp/icu CSVs into Azure SQL, cohort-filtered
  ingest_notes.py         Embeds discharge/radiology notes into Azure AI Search
  create_search_index.py  Defines the hybrid keyword+vector Search index
  cohort_utils.py, db.py  Shared helpers
config/                  Clinical term / ICD / itemid lookups (see above)
data/                    Gitignored — cohort ids + notes ground-truth, generated locally
```

## Status

- Structured data: loaded, all 18 tables, real MIMIC-IV.
- Notes: discharge summaries in progress; radiology not started.
- Read-only credentials (`app_readonly` SQL login, Search query key) are set
  up and are what's in `.env` — admin credentials are provisioning-only and
  not shared.
- Agent (router, Text-to-SQL, RAG retrieval) and Streamlit UI: not yet built —
  this is the next phase of work.
