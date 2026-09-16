"""Embeds discharge summaries / radiology reports and uploads them to the
Azure AI Search index created by create_search_index.py.

Filters to the same cohort subject_ids that ingest_structured.py wrote to
data/cohort_subject_ids.txt, so structured data and notes stay in sync — run
ingest_structured.py first.

Source data can be either:
  - real MIMIC-IV-Note CSVs (discharge.csv.gz / radiology.csv.gz — real data
    is credentialed-access-only, and needs separate PhysioNet approval from
    the base MIMIC-IV dataset). discharge.csv.gz covers ~330K notes and
    radiology.csv.gz ~2.3M reports across the *full* MIMIC-IV population, so
    these are streamed and filtered rather than loaded whole, or
  - the output of generate_synthetic_data.py (notes_metadata.csv + a .txt
    file per note).

Also writes data/cohort_notes.csv — the matched cohort's notes in full,
unchunked text, as an eval ground-truth reference kept independent of Azure
AI Search. The point is to be able to check "does the agent's answer match
what the note actually says" without trusting the retrieval pipeline to
grade its own homework — read this file directly in eval scripts rather
than re-querying Search for the comparison.

Usage:
    python scripts/ingest_notes.py --source /path/to/mimic-iv-note-2.2/note
    python scripts/ingest_notes.py --source data/synthetic
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from azure.search.documents import SearchClient
from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, AzureOpenAI
from tqdm import tqdm

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COHORT_IDS_PATH = PROJECT_ROOT / "data" / "cohort_subject_ids.txt"
GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "cohort_notes.csv"

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 200
EMBED_BATCH_SIZE = 100  # larger batches amortize per-request overhead: ~0.36s/chunk at 16 vs ~0.21s/chunk at 100
UPLOAD_BATCH_SIZE = 100

# Real MIMIC-IV-Note files and the note_type values found inside them.
# AR = addendum to a radiology report — still report content, grouped with RR.
REAL_NOTE_FILES = ["discharge", "radiology"]
REAL_NOTE_COLS = ["note_id", "subject_id", "hadm_id", "note_type", "charttime", "text"]
REAL_NOTE_TYPE_MAP = {"DS": "discharge_summary", "RR": "radiology_report", "AR": "radiology_report"}
REAL_CHUNK_ROWS = 20_000  # text-heavy rows — smaller chunks than the numeric hosp/icu tables


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def to_search_datetime(value: str) -> str:
    dt = datetime.fromisoformat(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_cohort_subject_ids() -> set[int] | None:
    if not COHORT_IDS_PATH.exists():
        print(f"Warning: {COHORT_IDS_PATH} not found — run ingest_structured.py "
              "first, or all notes in the source will be ingested unfiltered.")
        return None
    return {int(line) for line in COHORT_IDS_PATH.read_text().splitlines() if line.strip()}


RETRYABLE_ERRORS = (ServiceRequestError, ServiceResponseError, APIConnectionError, APITimeoutError,
                    ConnectionError, TimeoutError)


def with_retry(fn, retries: int = 4, base_delay: float = 5.0):
    """Retries transient network drops (we've hit RemoteDisconnected mid-run
    against both Azure SQL and Azure AI Search in this environment — not a
    one-off fluke, so long-running ingestion should tolerate it rather than
    dying and losing an hour of progress)."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except RETRYABLE_ERRORS as e:
            if attempt == retries:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"  transient error ({e.__class__.__name__}), retrying in {delay:.0f}s ...")
            time.sleep(delay)


def get_embeddings(client: AzureOpenAI, deployment: str, texts: list[str]) -> list[list[float]]:
    response = with_retry(lambda: client.embeddings.create(model=deployment, input=texts))
    return [item.embedding for item in response.data]


def resolve_real_note_path(source: Path, base_name: str) -> Path | None:
    for ext in (".csv", ".csv.gz"):
        candidate = source / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    return None


def is_real_format(source: Path) -> bool:
    return any(resolve_real_note_path(source, name) for name in REAL_NOTE_FILES)


def stream_real_notes(path: Path, subject_ids: set[int] | None):
    """Yields filtered DataFrame chunks of real MIMIC-IV-Note rows, with
    note_type normalized to discharge_summary/radiology_report (matching the
    synthetic generator's convention, so the rest of the pipeline and the
    search index's note_type field don't need to special-case the source)."""
    for chunk in pd.read_csv(path, usecols=REAL_NOTE_COLS, chunksize=REAL_CHUNK_ROWS):
        if subject_ids is not None:
            chunk = chunk[chunk["subject_id"].isin(subject_ids)]
        if chunk.empty:
            continue
        chunk = chunk.copy()
        chunk["note_type"] = chunk["note_type"].map(REAL_NOTE_TYPE_MAP).fillna(chunk["note_type"])
        yield chunk


def load_synthetic_notes(source: Path, subject_ids: set[int] | None):
    with open(source / "notes_metadata.csv") as f:
        note_rows = list(csv.DictReader(f))
    if subject_ids is not None:
        note_rows = [r for r in note_rows if int(r["subject_id"]) in subject_ids]
    for row in note_rows:
        yield {
            "note_id": row["note_id"],
            "subject_id": int(row["subject_id"]),
            "hadm_id": int(row["hadm_id"]),
            "note_type": row["note_type"],
            "charttime": row["charttime"],
            "text": (source / row["path"]).read_text(),
        }


class NoteProcessor:
    """Embeds + uploads note chunks to Search, and appends each original
    (unchunked) note to the local ground-truth CSV, in bounded-memory batches."""

    def __init__(self, embed_client, embedding_deployment, search_client, ground_truth_writer):
        self.embed_client = embed_client
        self.embedding_deployment = embedding_deployment
        self.search_client = search_client
        self.ground_truth_writer = ground_truth_writer
        self.pending_docs = []
        self.note_count = 0
        self.chunk_count = 0

    def add_note(self, note_id, subject_id, hadm_id, note_type, charttime, text):
        self.note_count += 1
        self.ground_truth_writer.writerow({
            "note_id": note_id, "subject_id": subject_id, "hadm_id": hadm_id if pd.notna(hadm_id) else "",
            "note_type": note_type, "charttime": charttime, "text": text,
        })
        for i, chunk in enumerate(chunk_text(text)):
            self.pending_docs.append({
                "id": f"{note_id}-{i}",
                "subject_id": int(subject_id),
                "hadm_id": int(hadm_id) if pd.notna(hadm_id) else None,
                "note_type": note_type,
                "charttime": to_search_datetime(charttime),
                "text": chunk,
            })
        if len(self.pending_docs) >= UPLOAD_BATCH_SIZE:
            self.flush()

    def flush(self):
        if not self.pending_docs:
            return
        for batch_start in range(0, len(self.pending_docs), EMBED_BATCH_SIZE):
            batch = self.pending_docs[batch_start:batch_start + EMBED_BATCH_SIZE]
            vectors = get_embeddings(self.embed_client, self.embedding_deployment, [d["text"] for d in batch])
            for doc, vector in zip(batch, vectors):
                doc["content_vector"] = vector
        for batch_start in range(0, len(self.pending_docs), UPLOAD_BATCH_SIZE):
            batch = self.pending_docs[batch_start:batch_start + UPLOAD_BATCH_SIZE]
            with_retry(lambda batch=batch: self.search_client.upload_documents(documents=batch))
        self.chunk_count += len(self.pending_docs)
        self.pending_docs = []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True,
                         help="Directory with discharge.csv.gz/radiology.csv.gz (real MIMIC-IV-Note), "
                              "or notes_metadata.csv + notes/ (generate_synthetic_data.py output)")
    parser.add_argument("--note-types", default=",".join(REAL_NOTE_FILES),
                         help=f"Comma-separated subset of {REAL_NOTE_FILES} to process "
                              "(real format only; ignored for synthetic data). Default: all.")
    args = parser.parse_args()

    source = Path(args.source)
    subject_ids = load_cohort_subject_ids()

    embed_client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_AI_FOUNDRY_ENDPOINT"],
        api_key=os.environ["AZURE_AI_FOUNDRY_API_KEY"],
        api_version="2024-06-01",
    )
    embedding_deployment = os.environ["AZURE_EMBEDDING_DEPLOYMENT"]

    # Uploading documents needs the admin key — the app-facing
    # AZURE_SEARCH_API_KEY is a read-only query key and can't write.
    search_client = SearchClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        index_name=os.environ.get("AZURE_SEARCH_INDEX_NAME", "clinical-notes"),
        credential=AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"]),
    )

    GROUND_TRUTH_PATH.parent.mkdir(exist_ok=True)
    with open(GROUND_TRUTH_PATH, "w", newline="") as gt_file:
        writer = csv.DictWriter(gt_file, fieldnames=["note_id", "subject_id", "hadm_id",
                                                       "note_type", "charttime", "text"])
        writer.writeheader()
        processor = NoteProcessor(embed_client, embedding_deployment, search_client, writer)

        if is_real_format(source):
            selected_types = [t.strip() for t in args.note_types.split(",") if t.strip()]
            for base_name in selected_types:
                path = resolve_real_note_path(source, base_name)
                if path is None:
                    print(f"  skipping {base_name}: not found under {source}")
                    continue
                print(f"Streaming {base_name} from {path} ...")
                for chunk in tqdm(stream_real_notes(path, subject_ids), desc=base_name, unit="chunk"):
                    for _, row in chunk.iterrows():
                        processor.add_note(row["note_id"], row["subject_id"], row["hadm_id"],
                                            row["note_type"], row["charttime"], row["text"])
        else:
            print(f"Reading synthetic notes from {source} ...")
            for note in load_synthetic_notes(source, subject_ids):
                processor.add_note(note["note_id"], note["subject_id"], note["hadm_id"],
                                    note["note_type"], note["charttime"], note["text"])

        processor.flush()

    print(f"Done. Embedded {processor.chunk_count} chunks from {processor.note_count} notes.")
    print(f"Ground-truth reference written to {GROUND_TRUTH_PATH}")


if __name__ == "__main__":
    main()
