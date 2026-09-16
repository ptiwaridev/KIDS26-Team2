# Dev environment setup

Two ways in — pick one. Both use the same [Dockerfile](Dockerfile), which is
also what we deploy to Azure Container Apps on day 3.

## Option A: VS Code Dev Container (recommended)

1. Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
   and Docker Desktop.
2. `cp .env.example .env` and fill in values (see [Environment variables](#environment-variables)
   below). This file must exist before opening the container — it's bind-mounted in.
3. Open the folder in VS Code, then **Reopen in Container** when prompted
   (or Cmd+Shift+P → "Dev Containers: Reopen in Container").
4. Once it builds, run `make run` in the integrated terminal and open
   http://localhost:8501.

## Option B: Docker Compose (no VS Code)

1. `cp .env.example .env` and fill in values.
2. `make docker-up` (or `docker compose up`).
3. Open http://localhost:8501.

## Option C: Local venv (no Docker)

Needs the [msodbcsql18 ODBC driver](https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)
installed on your machine for `pyodbc` to work.

1. `make setup` — creates `.venv`, installs pinned deps, copies `.env.example` to `.env`.
2. Fill in `.env`.
3. `source .venv/bin/activate && make run`.

## Environment variables

See [.env.example](.env.example) for the full list. You'll need, at minimum:

- **Azure SQL** connection details (structured MIMIC-IV subset tables)
- **Azure AI Search** endpoint + key (RAG index over discharge summaries / radiology reports)
- **Azure AI Foundry** endpoint + key (embeddings + Claude Sonnet 5 generation)

Ask whoever ran `scripts/provision_azure.sh` for real values, or leave
`USE_SYNTHETIC_DATA=true` and point at the shared synthetic-data Azure
SQL/Search instances.

## Provisioning Azure resources (once per team, not per person)

```
az login
SQL_ADMIN_PASSWORD='<pick one>' ./scripts/provision_azure.sh
```

Creates the resource group, Azure SQL server/DB, Azure AI Search service, and
an Azure AI Foundry resource with the `text-embedding-3-small` deployment. It
prints the `.env` values to paste in, and one manual step: deploying Claude
Sonnet 5 requires accepting Azure Marketplace terms in the Foundry portal
(not scriptable via `az cli`) — the script explains exactly what to click.

## Loading data

**Credentials note first**: `db-schema`, `ingest-structured`, `search-index`,
and `ingest-notes` all need *write* access, not what a normal dev session
uses — `AZURE_SQL_USERNAME`/`PASSWORD` must be the admin login (not
`app_readonly`) and `.env` must have `AZURE_SEARCH_ADMIN_KEY` set (not just
the read-only `AZURE_SEARCH_API_KEY` the app uses). Swap `.env` to admin
creds for this section, then swap back afterward — see the comment in
`.env.example`.

Every teammate without PhysioNet credentials works off generated synthetic
data (same schema as real MIMIC-IV, so nothing else changes when real data
swaps in):

```
make synthetic-data      # writes data/synthetic/ (CSVs + note .txt files)
make ingest-all           # schema -> structured data -> search index -> notes
```

`ingest-all` runs, in order: `db-schema` (applies [sql/schema.sql](sql/schema.sql)
via [scripts/apply_sql_file.py](scripts/apply_sql_file.py) — we don't use
`sqlcmd`, it isn't installed in the app container), `ingest-structured`
([scripts/ingest_structured.py](scripts/ingest_structured.py) — filters to
the cohorts in [config/cohorts.json](config/cohorts.json) and loads Azure
SQL), `search-index` ([scripts/create_search_index.py](scripts/create_search_index.py) —
creates the hybrid keyword+vector index), and `ingest-notes`
([scripts/ingest_notes.py](scripts/ingest_notes.py) — embeds notes for the same
cohort and uploads them). Run the steps individually if you need to re-run
just one.

Once loading is done, run `make readonly-login` (still with admin creds in
`.env`) to create the low-privilege `app_readonly` SQL login — this calls
[scripts/create_readonly_login.py](scripts/create_readonly_login.py), which
is idempotent (safe to re-run, won't overwrite an existing login's password).
It prints the values to put in `.env`. **Then swap `.env` back to those
read-only values for actual dev/app use** — never leave admin creds as the
app's default, and never share the admin password or `AZURE_SEARCH_ADMIN_KEY`
with the team (see [README.md](README.md#access)).

Credentialed members loading real data instead of synthetic:

```
python scripts/ingest_structured.py --source /path/to/mimic-iv-3.1/hosp \
    --icu-source /path/to/mimic-iv-3.1/icu   # only needed if icu/ isn't a sibling of hosp/
python scripts/ingest_notes.py --source /path/to/mimic-iv-note-2.2/note \
    --note-types discharge   # add ",radiology" only once discharge-only RAG is confirmed working
```

The cohort filter and everything downstream is identical to the synthetic
path. `--icu-source` supplies `icustays`/`chartevents`/`inputevents`/
`outputevents`, which live in MIMIC-IV's separate `icu/` folder — it defaults
to a sibling `icu/` directory next to `--source` if omitted. `labevents`,
`prescriptions`, and `chartevents` are streamed rather than loaded whole
(they're large — `chartevents.csv.gz` alone is ~430M rows) and can take a
while even filtered to our cohort; expect roughly 20-30 minutes for the
structured load and up to a couple hours for full notes ingestion depending
on scope (`--note-types discharge` alone is much faster than including
radiology too).

## Building the Text-to-SQL agent — read this first

See [README.md](README.md#data-scope) for which tables to build the prompt
around and why, and [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for what every
in-scope column actually means. Two config files exist specifically so the
agent doesn't have to guess at query time — use them instead of having the
agent look things up live:

- [config/clinical_terms.json](config/clinical_terms.json) — clinical term →
  ICD code prefixes (e.g. "sepsis" → its codes).
- [config/icu_item_lookup.json](config/icu_item_lookup.json) — verified
  itemid for each vital/fluid that matters, for the `chartevents`/
  `inputevents`/`outputevents` tables, if/when that stretch goal gets picked up.

## Real MIMIC-IV data — read before touching

Real patient data (MIMIC-IV / MIMIC-IV-Note) may only be accessed by
PhysioNet-credentialed team members, at every stage — including once it's
loaded into our Azure SQL / Azure AI Search instances. Everyone else works
against synthetic data with the same schema (`USE_SYNTHETIC_DATA=true`).
Never commit real data or point a shared/non-credentialed resource at it.

## Running tests

```
make test
```

## Troubleshooting

- **`.env` mount fails when opening the dev container**: you skipped step 2 —
  create `.env` before reopening in container.
- **`pyodbc` import/connection errors locally**: install the msodbcsql18
  driver (linked above), or just use Option A/B instead.
- **`SSL: CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate
  chain` calling Azure AI Search or Azure AI Foundry** (SQL connections
  unaffected): your network is doing corporate TLS inspection — check with
  `openssl s_client -connect <host>:443 -brief` and look at the `depth=1`
  issuer; ours turned out to be Cloudflare Zero Trust Gateway. The container
  doesn't trust that root CA by default even though your Mac already does.
  Fix, per `docker compose run`:
  1. Export the root CA from your Mac's keychain: `security find-certificate
     -a -c "<issuer name from openssl output>" -p /Library/Keychains/System.keychain
     > gateway-ca.pem`, then split it into one cert per file if it contains more
     than one (Debian's `update-ca-certificates` requires that).
  2. Mount each as `-v ./cert-N.pem:/usr/local/share/ca-certificates/cert-N.crt:ro`,
     set `-e REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt -e
     SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`, and run
     `update-ca-certificates` before your script (`requests`/`httpx` use their
     own bundled CA store via `certifi`, not the OS trust store, hence both
     env vars).
  This is specific to your machine/network — don't bake it into the shared
  Dockerfile.
- **`TypeError: Client.__init__() got an unexpected keyword argument
  'proxies'`** calling the `openai` client: `httpx>=0.28` dropped the
  `proxies` kwarg that `openai==1.44.1` still passes. Already pinned in
  `requirements.txt` (`httpx==0.27.2`) — if you still hit this, rebuild the
  image (`make docker-build`) to pick up the pin.
