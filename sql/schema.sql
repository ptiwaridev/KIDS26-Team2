-- Azure SQL schema for the MIMIC-IV subset (structured hosp-module tables only;
-- discharge summaries / radiology reports live in Azure AI Search, not here).
-- Column names/types mirror real MIMIC-IV so synthetic and real data are
-- interchangeable without app-layer changes.
--
-- Apply with:
--   sqlcmd -S <server>.database.windows.net -d <database> -U <user> -P <password> -i sql/schema.sql

IF OBJECT_ID('chartevents', 'U') IS NOT NULL DROP TABLE chartevents;
IF OBJECT_ID('inputevents', 'U') IS NOT NULL DROP TABLE inputevents;
IF OBJECT_ID('outputevents', 'U') IS NOT NULL DROP TABLE outputevents;
IF OBJECT_ID('d_items', 'U') IS NOT NULL DROP TABLE d_items;
-- transfers was removed from the schema (redundant with icustays/admissions/
-- services) but this drop stays so a database that still has it from an
-- older apply can be migrated cleanly.
IF OBJECT_ID('transfers', 'U') IS NOT NULL DROP TABLE transfers;
IF OBJECT_ID('icustays', 'U') IS NOT NULL DROP TABLE icustays;
IF OBJECT_ID('omr', 'U') IS NOT NULL DROP TABLE omr;
IF OBJECT_ID('services', 'U') IS NOT NULL DROP TABLE services;
IF OBJECT_ID('drgcodes', 'U') IS NOT NULL DROP TABLE drgcodes;
IF OBJECT_ID('procedures_icd', 'U') IS NOT NULL DROP TABLE procedures_icd;
IF OBJECT_ID('d_icd_procedures', 'U') IS NOT NULL DROP TABLE d_icd_procedures;
IF OBJECT_ID('microbiologyevents', 'U') IS NOT NULL DROP TABLE microbiologyevents;
IF OBJECT_ID('prescriptions', 'U') IS NOT NULL DROP TABLE prescriptions;
IF OBJECT_ID('labevents', 'U') IS NOT NULL DROP TABLE labevents;
IF OBJECT_ID('diagnoses_icd', 'U') IS NOT NULL DROP TABLE diagnoses_icd;
IF OBJECT_ID('admissions', 'U') IS NOT NULL DROP TABLE admissions;
IF OBJECT_ID('d_labitems', 'U') IS NOT NULL DROP TABLE d_labitems;
IF OBJECT_ID('d_icd_diagnoses', 'U') IS NOT NULL DROP TABLE d_icd_diagnoses;
IF OBJECT_ID('patients', 'U') IS NOT NULL DROP TABLE patients;

CREATE TABLE patients (
    subject_id          INT             NOT NULL PRIMARY KEY,
    gender              CHAR(1)         NOT NULL,
    anchor_age          INT             NOT NULL,
    anchor_year         INT             NOT NULL,
    anchor_year_group   VARCHAR(20)     NOT NULL,
    dod                 DATE            NULL
);

CREATE TABLE admissions (
    hadm_id             INT             NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    admittime           DATETIME2       NOT NULL,
    dischtime           DATETIME2       NOT NULL,
    deathtime           DATETIME2       NULL,
    admission_type      VARCHAR(40)     NOT NULL,
    admission_location  VARCHAR(60)     NULL,
    discharge_location  VARCHAR(60)     NULL,
    insurance           VARCHAR(40)     NULL,
    language            VARCHAR(40)     NULL,  -- real MIMIC-IV values run longer than "ENGLISH"
    marital_status      VARCHAR(20)     NULL,
    race                VARCHAR(80)     NULL,
    hospital_expire_flag BIT            NOT NULL DEFAULT 0
);
CREATE INDEX ix_admissions_subject_id ON admissions(subject_id);

CREATE TABLE d_icd_diagnoses (
    icd_code            VARCHAR(10)     NOT NULL,
    icd_version         TINYINT         NOT NULL,
    long_title          VARCHAR(255)    NOT NULL,
    PRIMARY KEY (icd_code, icd_version)
);

CREATE TABLE diagnoses_icd (
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    seq_num             INT             NOT NULL,
    icd_code            VARCHAR(10)     NOT NULL,
    icd_version         TINYINT         NOT NULL,
    PRIMARY KEY (hadm_id, seq_num),
    FOREIGN KEY (icd_code, icd_version) REFERENCES d_icd_diagnoses(icd_code, icd_version)
);
CREATE INDEX ix_diagnoses_icd_subject_id ON diagnoses_icd(subject_id);
CREATE INDEX ix_diagnoses_icd_code ON diagnoses_icd(icd_code, icd_version);

CREATE TABLE d_labitems (
    itemid              INT             NOT NULL PRIMARY KEY,
    label               VARCHAR(200)    NULL,  -- a handful of real MIMIC-IV rows have blank labels
    fluid               VARCHAR(50)     NULL,
    category            VARCHAR(50)     NULL
);

CREATE TABLE labevents (
    labevent_id         BIGINT          NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NULL REFERENCES admissions(hadm_id),
    itemid              INT             NOT NULL REFERENCES d_labitems(itemid),
    charttime           DATETIME2       NOT NULL,
    valuenum            FLOAT           NULL,
    valueuom            VARCHAR(20)     NULL,
    flag                VARCHAR(10)     NULL
);
CREATE INDEX ix_labevents_subject_id ON labevents(subject_id);
CREATE INDEX ix_labevents_hadm_id ON labevents(hadm_id);
CREATE INDEX ix_labevents_itemid ON labevents(itemid);

CREATE TABLE prescriptions (
    -- pharmacy_id is NOT unique per row in real MIMIC-IV (a single pharmacy
    -- order can produce multiple rows, e.g. an IV base solution plus its
    -- additive drug share one pharmacy_id) — surrogate key instead.
    prescription_id     BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    pharmacy_id         BIGINT          NOT NULL,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    starttime           DATETIME2       NULL,
    stoptime            DATETIME2       NULL,
    drug                VARCHAR(200)    NOT NULL,
    dose_val_rx         VARCHAR(50)     NULL,
    dose_unit_rx        VARCHAR(50)     NULL,
    route               VARCHAR(50)     NULL
);
CREATE INDEX ix_prescriptions_subject_id ON prescriptions(subject_id);
CREATE INDEX ix_prescriptions_hadm_id ON prescriptions(hadm_id);
CREATE INDEX ix_prescriptions_pharmacy_id ON prescriptions(pharmacy_id);

-- Everything below was added to widen the subset for epidemiology/health-
-- services research questions beyond acute-care Text-to-SQL lookups:
-- infection/organism data, interventions, ICU severity/escalation, care
-- pathway, case-mix, and longitudinal outpatient vitals for the HF cohort.

CREATE TABLE microbiologyevents (
    microevent_id       BIGINT          NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NULL REFERENCES admissions(hadm_id),
    chartdate           DATE            NULL,
    charttime           DATETIME2       NULL,
    spec_type_desc      VARCHAR(80)     NULL,   -- e.g. "BLOOD CULTURE"
    test_name           VARCHAR(100)    NOT NULL,
    org_name            VARCHAR(120)    NULL,   -- organism identified, NULL = no growth
    ab_name             VARCHAR(50)     NULL,   -- antibiotic tested, if any
    interpretation      VARCHAR(5)      NULL    -- S/I/R/P susceptibility result
);
CREATE INDEX ix_microbiologyevents_subject_id ON microbiologyevents(subject_id);
CREATE INDEX ix_microbiologyevents_hadm_id ON microbiologyevents(hadm_id);

CREATE TABLE d_icd_procedures (
    icd_code            VARCHAR(10)     NOT NULL,
    icd_version         TINYINT         NOT NULL,
    long_title          VARCHAR(200)    NOT NULL,
    PRIMARY KEY (icd_code, icd_version)
);

CREATE TABLE procedures_icd (
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    seq_num             INT             NOT NULL,
    chartdate           DATE            NOT NULL,
    icd_code            VARCHAR(10)     NOT NULL,
    icd_version         TINYINT         NOT NULL,
    PRIMARY KEY (hadm_id, seq_num),
    FOREIGN KEY (icd_code, icd_version) REFERENCES d_icd_procedures(icd_code, icd_version)
);
CREATE INDEX ix_procedures_icd_subject_id ON procedures_icd(subject_id);

CREATE TABLE drgcodes (
    -- no natural single-row key: one admission can have multiple DRG rows
    -- (e.g. one APR row and one HCFA row)
    drg_id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    drg_type            VARCHAR(10)     NOT NULL,
    drg_code            INT             NOT NULL,
    description         VARCHAR(150)    NOT NULL,
    drg_severity        TINYINT         NULL,
    drg_mortality       TINYINT         NULL
);
CREATE INDEX ix_drgcodes_hadm_id ON drgcodes(hadm_id);

CREATE TABLE services (
    -- no natural single-row key: an admission can have multiple service
    -- transfers over its course
    service_id          BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    transfertime         DATETIME2       NOT NULL,
    prev_service        VARCHAR(10)     NULL,
    curr_service        VARCHAR(10)     NOT NULL
);
CREATE INDEX ix_services_hadm_id ON services(hadm_id);

CREATE TABLE omr (
    -- Outpatient vitals/measurements (weight, BP, BMI) — linked to subject_id
    -- only, not hadm_id, since these are longitudinal outpatient readings,
    -- not tied to a specific admission. Useful for HF trend research.
    omr_id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    chartdate           DATE            NOT NULL,
    seq_num             INT             NOT NULL,
    result_name         VARCHAR(50)     NOT NULL,
    result_value        VARCHAR(20)     NOT NULL
);
CREATE INDEX ix_omr_subject_id ON omr(subject_id);

CREATE TABLE icustays (
    stay_id             BIGINT          NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    first_careunit      VARCHAR(80)     NOT NULL,
    last_careunit       VARCHAR(80)     NOT NULL,
    intime              DATETIME2       NOT NULL,
    outtime             DATETIME2       NULL,
    los                 FLOAT           NULL   -- length of stay, in days
);
CREATE INDEX ix_icustays_subject_id ON icustays(subject_id);
CREATE INDEX ix_icustays_hadm_id ON icustays(hadm_id);

-- ICU event-level tables: bedside vitals, IV fluids/vasopressors, and urine
-- output. These enable severity scoring (SOFA/APACHE) and sepsis fluid-
-- resuscitation research that lab/prescription data alone can't support.
-- All three are keyed to icustays via stay_id, not just hadm_id.

CREATE TABLE d_items (
    itemid              INT             NOT NULL PRIMARY KEY,
    label               VARCHAR(150)    NOT NULL,
    abbreviation        VARCHAR(100)    NULL,
    category            VARCHAR(60)     NULL,
    unitname            VARCHAR(40)     NULL,
    param_type          VARCHAR(30)     NULL
);

CREATE TABLE chartevents (
    -- no natural row id in real MIMIC-IV chartevents — surrogate key
    chartevent_id       BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    stay_id             BIGINT          NOT NULL REFERENCES icustays(stay_id),
    itemid              INT             NOT NULL REFERENCES d_items(itemid),
    charttime           DATETIME2       NOT NULL,
    valuenum            FLOAT           NULL,
    valueuom            VARCHAR(40)     NULL
);
CREATE INDEX ix_chartevents_stay_id ON chartevents(stay_id);
CREATE INDEX ix_chartevents_itemid ON chartevents(itemid);

CREATE TABLE inputevents (
    -- no natural row id used as PK here — surrogate key
    input_id            BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    stay_id             BIGINT          NOT NULL REFERENCES icustays(stay_id),
    itemid              INT             NOT NULL REFERENCES d_items(itemid),
    starttime           DATETIME2       NOT NULL,
    endtime             DATETIME2       NULL,
    amount              FLOAT           NULL,
    amountuom           VARCHAR(40)     NULL,
    rate                FLOAT           NULL,
    rateuom             VARCHAR(30)     NULL,
    ordercategorydescription VARCHAR(30) NULL   -- e.g. "Bolus" vs "Continuous"
);
CREATE INDEX ix_inputevents_stay_id ON inputevents(stay_id);
CREATE INDEX ix_inputevents_itemid ON inputevents(itemid);

CREATE TABLE outputevents (
    output_id           BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    subject_id          INT             NOT NULL REFERENCES patients(subject_id),
    hadm_id             INT             NOT NULL REFERENCES admissions(hadm_id),
    stay_id             BIGINT          NOT NULL REFERENCES icustays(stay_id),
    itemid              INT             NOT NULL REFERENCES d_items(itemid),
    charttime           DATETIME2       NOT NULL,
    value               FLOAT           NULL,
    valueuom            VARCHAR(10)     NULL
);
CREATE INDEX ix_outputevents_stay_id ON outputevents(stay_id);
CREATE INDEX ix_outputevents_itemid ON outputevents(itemid);
