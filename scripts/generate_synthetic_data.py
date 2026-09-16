"""Generates synthetic data matching the MIMIC-IV subset schema (sql/schema.sql)
so teammates without PhysioNet credentials can develop against realistic-shaped
data. NOT derived from or resembling any real patient — purely templated/random.

Usage:
    python scripts/generate_synthetic_data.py --n-patients 500 --out-dir data/synthetic
"""
import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

fake = Faker()

# (icd_code, icd_version, long_title, cohort) — cohort is None for generic comorbidities
ICD_CATALOG = [
    ("A419", 10, "Sepsis, unspecified organism", "sepsis"),
    ("A411", 10, "Sepsis due to other specified staphylococcus", "sepsis"),
    ("R6521", 10, "Severe sepsis with septic shock", "sepsis"),
    ("I5023", 10, "Acute on chronic systolic heart failure", "heart_failure"),
    ("I5033", 10, "Acute on chronic diastolic heart failure", "heart_failure"),
    ("I509", 10, "Heart failure, unspecified", "heart_failure"),
    ("N179", 10, "Acute kidney failure, unspecified", None),
    ("N189", 10, "Chronic kidney disease, unspecified", None),
    ("E119", 10, "Type 2 diabetes mellitus without complications", None),
    ("I10", 10, "Essential (primary) hypertension", None),
    ("J189", 10, "Pneumonia, unspecified organism", None),
    ("D649", 10, "Anemia, unspecified", None),
]

D_LABITEMS = [
    (50813, "Lactate", "Blood", "Chemistry"),
    (50971, "Potassium", "Blood", "Chemistry"),
    (50983, "Sodium", "Blood", "Chemistry"),
    (50912, "Creatinine", "Blood", "Chemistry"),
    (51301, "White Blood Cells", "Blood", "Hematology"),
    (51222, "Hemoglobin", "Blood", "Hematology"),
    (50963, "NTproBNP", "Blood", "Chemistry"),
    (51003, "Troponin T", "Blood", "Chemistry"),
]
# (mean, std, unit) for a "normal" patient and for a patient in the given cohort
LAB_RANGES = {
    50813: {"normal": (1.0, 0.4), "sepsis": (4.5, 1.8), "unit": "mmol/L"},
    50971: {"normal": (4.2, 0.4), "sepsis": (4.0, 0.6), "unit": "mEq/L"},
    50983: {"normal": (140, 3), "sepsis": (137, 4), "unit": "mEq/L"},
    50912: {"normal": (0.9, 0.2), "sepsis": (1.6, 0.6), "unit": "mg/dL"},
    51301: {"normal": (7.5, 1.5), "sepsis": (15.0, 4.0), "unit": "K/uL"},
    51222: {"normal": (13.5, 1.2), "sepsis": (10.5, 1.5), "unit": "g/dL"},
    50963: {"normal": (100, 50), "heart_failure": (3500, 1200), "unit": "pg/mL"},
    51003: {"normal": (0.01, 0.005), "heart_failure": (0.08, 0.03), "unit": "ng/mL"},
}

SEPSIS_DRUGS = ["Vancomycin", "Piperacillin-Tazobactam", "Cefepime", "Meropenem", "Norepinephrine"]
HF_DRUGS = ["Furosemide", "Lisinopril", "Metoprolol Succinate", "Spironolactone", "Carvedilol"]
GENERIC_DRUGS = ["Acetaminophen", "Insulin Regular", "Aspirin"]

ADMISSION_TYPES = ["EW EMER.", "URGENT", "ELECTIVE", "OBSERVATION ADMIT"]
RACES = ["WHITE", "BLACK/AFRICAN AMERICAN", "HISPANIC/LATINO", "ASIAN", "UNKNOWN"]
MARITAL = ["MARRIED", "SINGLE", "DIVORCED", "WIDOWED"]
INSURANCE = ["Medicare", "Medicaid", "Private", "Other"]


def weighted_cohort(rng: random.Random) -> str:
    return rng.choices(["sepsis", "heart_failure", "none"], weights=[0.4, 0.4, 0.2])[0]


def gen_patients(rng: random.Random, n: int):
    rows = []
    cohort_by_subject = {}
    for i in range(n):
        subject_id = 10000000 + i
        cohort = weighted_cohort(rng)
        cohort_by_subject[subject_id] = cohort
        rows.append({
            "subject_id": subject_id,
            "gender": rng.choice(["M", "F"]),
            "anchor_age": rng.randint(28, 92),
            "anchor_year": rng.randint(2110, 2210),
            "anchor_year_group": "2017 - 2019",
            "dod": "",
        })
    return rows, cohort_by_subject


def gen_admissions_and_diagnoses(rng: random.Random, patients, cohort_by_subject):
    admissions, diagnoses = [], []
    hadm_id = 20000000
    for p in patients:
        subject_id = p["subject_id"]
        cohort = cohort_by_subject[subject_id]
        n_admissions = rng.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
        admit_time = datetime(rng.randint(2110, 2208), rng.randint(1, 12), rng.randint(1, 28))

        for _ in range(n_admissions):
            los_hours = rng.randint(24, 240)
            dischtime = admit_time + timedelta(hours=los_hours)
            expire = cohort == "sepsis" and rng.random() < 0.08
            admissions.append({
                "hadm_id": hadm_id,
                "subject_id": subject_id,
                "admittime": admit_time.isoformat(sep=" "),
                "dischtime": dischtime.isoformat(sep=" "),
                "deathtime": dischtime.isoformat(sep=" ") if expire else "",
                "admission_type": rng.choice(ADMISSION_TYPES),
                "admission_location": "EMERGENCY ROOM",
                "discharge_location": "DIED" if expire else rng.choice(["HOME", "SKILLED NURSING FACILITY", "HOME HEALTH CARE"]),
                "insurance": rng.choice(INSURANCE),
                "language": "ENGLISH",
                "marital_status": rng.choice(MARITAL),
                "race": rng.choice(RACES),
                "hospital_expire_flag": 1 if expire else 0,
            })

            codes = [c for c in ICD_CATALOG if c[3] == cohort] if cohort != "none" else []
            seq = 1
            if codes:
                primary = rng.choice(codes)
                diagnoses.append({"subject_id": subject_id, "hadm_id": hadm_id, "seq_num": seq,
                                   "icd_code": primary[0], "icd_version": primary[1]})
                seq += 1
            for _ in range(rng.randint(1, 4)):
                comorbid = rng.choice(ICD_CATALOG)
                diagnoses.append({"subject_id": subject_id, "hadm_id": hadm_id, "seq_num": seq,
                                   "icd_code": comorbid[0], "icd_version": comorbid[1]})
                seq += 1

            hadm_id += 1
            admit_time = dischtime + timedelta(days=rng.randint(30, 400))

    return admissions, diagnoses


def gen_labevents(rng: random.Random, admissions, cohort_by_subject):
    rows, labevent_id = [], 90000000
    for adm in admissions:
        cohort = cohort_by_subject[adm["subject_id"]]
        admit_time = datetime.fromisoformat(adm["admittime"])
        for itemid, *_ in D_LABITEMS:
            ranges = LAB_RANGES[itemid]
            mean, std = ranges.get(cohort, ranges["normal"])
            for k in range(rng.randint(2, 5)):
                value = max(0.001, rng.gauss(mean, std))
                rows.append({
                    "labevent_id": labevent_id,
                    "subject_id": adm["subject_id"],
                    "hadm_id": adm["hadm_id"],
                    "itemid": itemid,
                    "charttime": (admit_time + timedelta(hours=6 * k)).isoformat(sep=" "),
                    "valuenum": round(value, 2),
                    "valueuom": ranges["unit"],
                    "flag": "abnormal" if cohort in ("sepsis", "heart_failure") and cohort in ranges else "",
                })
                labevent_id += 1
    return rows


def gen_prescriptions(rng: random.Random, admissions, cohort_by_subject):
    rows, pharmacy_id = [], 70000000
    for adm in admissions:
        cohort = cohort_by_subject[adm["subject_id"]]
        drug_pool = {"sepsis": SEPSIS_DRUGS, "heart_failure": HF_DRUGS}.get(cohort, []) + GENERIC_DRUGS
        admit_time = datetime.fromisoformat(adm["admittime"])
        for drug in rng.sample(drug_pool, k=min(len(drug_pool), rng.randint(2, 5))):
            start = admit_time + timedelta(hours=rng.randint(0, 24))
            rows.append({
                "pharmacy_id": pharmacy_id,
                "subject_id": adm["subject_id"],
                "hadm_id": adm["hadm_id"],
                "starttime": start.isoformat(sep=" "),
                "stoptime": (start + timedelta(days=rng.randint(1, 7))).isoformat(sep=" "),
                "drug": drug,
                "dose_val_rx": str(rng.choice([5, 10, 20, 40, 500, 1000])),
                "dose_unit_rx": rng.choice(["mg", "mg/kg"]),
                "route": rng.choice(["IV", "PO", "IM"]),
            })
            pharmacy_id += 1
    return rows


DISCHARGE_TEMPLATE = """\
Sex:   {gender}
Service: MEDICINE

HISTORY OF PRESENT ILLNESS:
{age} year old patient presenting with symptoms concerning for {condition}. \
{hpi_detail}

HOSPITAL COURSE:
Patient was admitted and treated per {condition} protocol. {course_detail} \
Labs notable for {lab_detail}. Patient's condition {outcome} over the course \
of admission.

MEDICATIONS ON DISCHARGE:
{meds}

DISCHARGE DIAGNOSIS:
{condition}

DISCHARGE CONDITION:
{discharge_condition}
"""

RADIOLOGY_TEMPLATE = """\
EXAMINATION: CHEST (PORTABLE AP)

INDICATION: {age} year old with {condition}, evaluate for acute process.

FINDINGS: {findings}

IMPRESSION: {impression}
"""

CONDITION_TEXT = {
    "sepsis": {
        "hpi": "fever, tachycardia, and hypotension concerning for sepsis of unclear source.",
        "course": "Blood cultures were drawn and broad-spectrum antibiotics initiated.",
        "lab": "elevated lactate and leukocytosis",
        "findings": "Patchy opacity in the right lower lobe, possibly reflecting infection.",
        "impression": "Findings compatible with pneumonia in the appropriate clinical setting.",
    },
    "heart_failure": {
        "hpi": "progressive dyspnea on exertion and lower extremity edema concerning for acute decompensated heart failure.",
        "course": "Diuresis was initiated with close monitoring of renal function and daily weights.",
        "lab": "elevated NT-proBNP",
        "findings": "Cardiomegaly with mild pulmonary vascular congestion.",
        "impression": "Findings consistent with mild pulmonary edema in the setting of heart failure.",
    },
    "none": {
        "hpi": "a chronic medical condition requiring routine inpatient management.",
        "course": "Patient was managed supportively with no acute complications.",
        "lab": "values within expected range for the patient's baseline",
        "findings": "No acute cardiopulmonary process.",
        "impression": "No acute findings.",
    },
}


def gen_notes(rng: random.Random, admissions, patients_by_id, cohort_by_subject, out_dir: Path):
    (out_dir / "notes" / "discharge").mkdir(parents=True, exist_ok=True)
    (out_dir / "notes" / "radiology").mkdir(parents=True, exist_ok=True)
    metadata = []
    note_id = 1

    for adm in admissions:
        subject_id, hadm_id = adm["subject_id"], adm["hadm_id"]
        cohort = cohort_by_subject[subject_id]
        text_key = cohort if cohort in CONDITION_TEXT else "none"
        t = CONDITION_TEXT[text_key]
        patient = patients_by_id[subject_id]
        dischtime = adm["dischtime"]
        expired = adm["hospital_expire_flag"] == 1

        discharge_text = DISCHARGE_TEMPLATE.format(
            gender=patient["gender"], age=patient["anchor_age"],
            condition=cohort.replace("_", " ") if cohort != "none" else "the admitting diagnosis",
            hpi_detail=t["hpi"], course_detail=t["course"], lab_detail=t["lab"],
            outcome="deteriorated" if expired else "improved",
            meds=", ".join(rng.sample(SEPSIS_DRUGS + HF_DRUGS + GENERIC_DRUGS, k=3)),
            discharge_condition="Expired" if expired else rng.choice(["Stable", "Improved"]),
        )
        path = out_dir / "notes" / "discharge" / f"{hadm_id}.txt"
        path.write_text(discharge_text)
        metadata.append({"note_id": note_id, "subject_id": subject_id, "hadm_id": hadm_id,
                          "note_type": "discharge_summary", "charttime": dischtime,
                          "path": str(path.relative_to(out_dir))})
        note_id += 1

        if cohort in ("sepsis", "heart_failure") and rng.random() < 0.6:
            radiology_text = RADIOLOGY_TEMPLATE.format(
                age=patient["anchor_age"], condition=cohort.replace("_", " "),
                findings=t["findings"], impression=t["impression"],
            )
            path = out_dir / "notes" / "radiology" / f"{hadm_id}_1.txt"
            path.write_text(radiology_text)
            metadata.append({"note_id": note_id, "subject_id": subject_id, "hadm_id": hadm_id,
                              "note_type": "radiology_report", "charttime": adm["admittime"],
                              "path": str(path.relative_to(out_dir))})
            note_id += 1

    return metadata


def write_csv(path: Path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-patients", type=int, default=500)
    parser.add_argument("--out-dir", type=str, default="data/synthetic")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    Faker.seed(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    patients, cohort_by_subject = gen_patients(rng, args.n_patients)
    patients_by_id = {p["subject_id"]: p for p in patients}
    admissions, diagnoses = gen_admissions_and_diagnoses(rng, patients, cohort_by_subject)
    labevents = gen_labevents(rng, admissions, cohort_by_subject)
    prescriptions = gen_prescriptions(rng, admissions, cohort_by_subject)
    notes_metadata = gen_notes(rng, admissions, patients_by_id, cohort_by_subject, out_dir)

    write_csv(out_dir / "patients.csv", patients, list(patients[0].keys()))
    write_csv(out_dir / "admissions.csv", admissions, list(admissions[0].keys()))
    write_csv(out_dir / "diagnoses_icd.csv", diagnoses, list(diagnoses[0].keys()))
    write_csv(out_dir / "d_icd_diagnoses.csv",
              [{"icd_code": c[0], "icd_version": c[1], "long_title": c[2]} for c in ICD_CATALOG],
              ["icd_code", "icd_version", "long_title"])
    write_csv(out_dir / "d_labitems.csv",
              [{"itemid": i, "label": l, "fluid": f, "category": c} for i, l, f, c in D_LABITEMS],
              ["itemid", "label", "fluid", "category"])
    write_csv(out_dir / "labevents.csv", labevents, list(labevents[0].keys()))
    write_csv(out_dir / "prescriptions.csv", prescriptions, list(prescriptions[0].keys()))
    write_csv(out_dir / "notes_metadata.csv", notes_metadata, list(notes_metadata[0].keys()))

    print(f"Generated {len(patients)} patients, {len(admissions)} admissions, "
          f"{len(notes_metadata)} notes -> {out_dir}/")


if __name__ == "__main__":
    main()
