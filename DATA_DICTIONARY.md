# Data Dictionary

What's actually in Azure SQL and Azure AI Search, scoped to the tables the
agent build should target (see [README.md](README.md#data-scope) for why
these specific tables and not the full 18). Row counts are from the real
1,500-patient MIMIC-IV cohort as of the last ingestion run — re-check if the
cohort changes. Full column definitions with types/constraints are always
authoritative in [sql/schema.sql](sql/schema.sql); this document explains
what each column *means*, which schema.sql doesn't.

Two things apply across every table below:
- `subject_id` (patient) and `hadm_id` (hospital admission) are the join
  keys everywhere. A patient has one `subject_id` for life; one admission is
  one `hadm_id`. Most tables have both; a few (`labevents`,
  `microbiologyevents`) allow `hadm_id` to be `NULL` for events not tied to
  an admission — don't drop those rows by filtering on `hadm_id` alone.
- ICD codes always come with an `icd_version` (9 or 10) — the same code
  string can mean different things across versions, so joins to
  `d_icd_diagnoses` must match on **both** `icd_code` and `icd_version`.
- Don't hand-write ICD-code or itemid lookups — [config/clinical_terms.json](config/clinical_terms.json)
  already maps clinical terms ("sepsis") to the right ICD prefixes, and
  [config/icu_item_lookup.json](config/icu_item_lookup.json) does the same
  for ICU vital/fluid itemids if that work gets picked up later.

## patients — 1,500 rows

Who the patient is. One row per patient, static (not longitudinal).

| Column | Meaning |
|---|---|
| `subject_id` (PK) | Unique patient ID |
| `gender` | `M` or `F` |
| `anchor_age` | Patient's age at `anchor_year` |
| `anchor_year` | A de-identified reference year — real calendar dates are shifted per-patient for de-identification, so this is the anchor point everything else (admission times, etc.) is relative to, not a real calendar year |
| `anchor_year_group` | A 3-year bucket (e.g. `"2017 - 2019"`) `anchor_year` falls in, for population-level time context without exposing exact shifted dates |
| `dod` | Date of death, if known; `NULL` if the patient is alive per available records |

## admissions — 6,073 rows

One row per hospital admission. A patient can have several (our cohort
averages ~4 per patient).

| Column | Meaning |
|---|---|
| `hadm_id` (PK) | Unique admission ID |
| `subject_id` (FK → patients) | |
| `admittime` / `dischtime` | Admission / discharge timestamps |
| `deathtime` | Time of in-hospital death, if this admission ended in death |
| `admission_type` | e.g. `EW EMER.`, `URGENT`, `ELECTIVE`, `OBSERVATION ADMIT`, `SURGICAL SAME DAY ADMISSION` |
| `admission_location` / `discharge_location` | Where the patient came from / went to (e.g. `EMERGENCY ROOM`, `HOME`, `SKILLED NURSING FACILITY`) |
| `insurance` | Payer type: `Medicare`, `Medicaid`, `Private`, `Other` |
| `language` | Patient's language |
| `marital_status`, `race` | Self-explanatory; both nullable |
| `hospital_expire_flag` | `1` if the patient died during *this* admission, else `0` |

## diagnoses_icd — 63,358 rows (+ d_icd_diagnoses — 112,107 rows)

The diagnoses assigned to each admission. `d_icd_diagnoses` is the full
ICD-9/10 dictionary (unfiltered — every code, not just ones our cohort uses).

| Column | Meaning |
|---|---|
| `subject_id`, `hadm_id` (FK) | |
| `seq_num` | Rank of this diagnosis on the admission — `1` is the primary diagnosis, higher numbers are secondary diagnoses/comorbidities |
| `icd_code`, `icd_version` (FK → d_icd_diagnoses) | The code; version disambiguates ICD-9 vs ICD-10 |
| *(d_icd_diagnoses)* `long_title` | Human-readable description of the code |

Note: a patient's *cohort-defining* diagnosis (sepsis or heart failure) isn't
necessarily `seq_num = 1` — cohort membership is "any diagnosis matches,"
not "primary diagnosis matches." Don't assume `seq_num = 1` is the reason
they're in the cohort.

## labevents — 1,097,794 rows (+ d_labitems — 1,650 rows)

Lab test results. `d_labitems` is the dictionary of lab test types.

| Column | Meaning |
|---|---|
| `labevent_id` (PK) | Unique per row (a real MIMIC-IV column, not a surrogate) |
| `subject_id`, `hadm_id` | `hadm_id` is nullable — some labs are drawn outside a specific admission |
| `itemid` (FK → d_labitems) | Which lab test |
| `charttime` | When the specimen was measured |
| `valuenum` | The numeric result |
| `valueuom` | Unit of measure |
| `flag` | `"abnormal"` if outside the reference range, else `NULL` |
| *(d_labitems)* `label`, `fluid`, `category` | Test name, specimen type (e.g. `Blood`), category (e.g. `Chemistry`, `Hematology`) |

## prescriptions — 232,052 rows

Medications ordered.

| Column | Meaning |
|---|---|
| `prescription_id` (PK) | Surrogate key — see note below |
| `pharmacy_id` | Groups rows from the same pharmacy order. **Not unique per row**: one order can produce several rows (e.g. an IV base solution and its additive drug share a `pharmacy_id`) — this is why there's a separate surrogate `prescription_id` |
| `subject_id`, `hadm_id` | |
| `starttime` / `stoptime` | Nullable — some rows lack exact times |
| `drug` | Medication name |
| `dose_val_rx` / `dose_unit_rx` | Dose amount and unit |
| `route` | `PO`, `IV`, `IM`, etc. |

## microbiologyevents — 62,671 rows

Cultures drawn and their results — the core sepsis/infection/antimicrobial-
resistance table.

| Column | Meaning |
|---|---|
| `microevent_id` (PK) | |
| `subject_id`, `hadm_id` | `hadm_id` nullable — some cultures are drawn pre-admission or outpatient; don't filter these out by requiring `hadm_id` |
| `chartdate` / `charttime` | When the specimen was collected; both nullable |
| `spec_type_desc` | Specimen type, e.g. `"BLOOD CULTURE"`, `"URINE"`, `"SWAB"` |
| `test_name` | The test performed |
| `org_name` | Organism identified. **`NULL` means no growth** (negative culture), not missing data |
| `ab_name` | Antibiotic tested against the organism. `NULL` whenever `org_name` is `NULL` (no organism → nothing to test susceptibility against) |
| `interpretation` | Susceptibility result: `S` (susceptible), `I` (intermediate), `R` (resistant), or `P` (positive, for tests without a susceptibility panel) |

## icustays — 1,277 rows

ICU admission episodes. Not every admission has one — only ~21% of our
cohort's admissions involved the ICU.

| Column | Meaning |
|---|---|
| `stay_id` (PK) | |
| `subject_id`, `hadm_id` | |
| `first_careunit` / `last_careunit` | ICU unit type at the start/end of the stay (e.g. `"Medical Intensive Care Unit (MICU)"`) — can differ if the patient was transferred between ICU types mid-stay |
| `intime` / `outtime` | ICU admission/discharge times; `outtime` is nullable for stays still ongoing at data cutoff |
| `los` | Length of stay, in days (fractional, e.g. `3.89`) |

## discharge summaries — Azure AI Search (`clinical-notes` index)

Not a SQL table. Discharge summary text, chunked (~3000 chars, 200 overlap)
and embedded with `text-embedding-3-small`. Indexed fields:

| Field | Meaning |
|---|---|
| `id` | `{note_id}-{chunk_index}` |
| `subject_id`, `hadm_id` | Filterable — this is how the agent chains "SQL finds cohort → notes lookup" (`search.in(subject_id, ...)`) |
| `note_type` | `"discharge_summary"` (radiology reports use `"radiology_report"` if/when those get ingested) |
| `charttime` | When the note was written |
| `text` | The chunk's text (searchable, hybrid keyword+vector) |
| `content_vector` | The embedding — not retrievable via plain queries, only used for vector search |

The full, unchunked source text for every ingested note is also written
locally to `data/cohort_notes.csv` as an eval ground truth — **gitignored,
and just as credentialed-access-only as everything else**, since it's real
note text. See [README.md](README.md#access) before touching it.

## Loaded, but not in current scope

These exist in the database (ingestion cost nothing to leave them) but the
agent build isn't targeting them for this sprint — see
[README.md](README.md#data-scope) for why. Full definitions in
[sql/schema.sql](sql/schema.sql) if this changes:

- `procedures_icd` + `d_icd_procedures` — procedures performed per admission
- `drgcodes` — billing/case-mix codes with severity & mortality risk scores
- `services` — which clinical service treated the patient, and transfers between services
- `omr` — longitudinal outpatient vitals (weight, BP), not tied to an admission
- `chartevents`, `inputevents`, `outputevents`, `d_items` — ICU bedside vitals, IV fluids/vasopressors, and urine output; itemid-keyed (needs `config/icu_item_lookup.json`), which is why these are a stretch goal, not core
