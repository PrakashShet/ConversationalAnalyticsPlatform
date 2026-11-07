# `data/` directory

Working data for the platform. Subfolders:

| Folder | Purpose |
|---|---|
| `raw/` | Drop your source CSV files here (subfolders allowed — see below). |
| `samples/` | Example/demo datasets shipped with the project. |
| `exports/` | Default location for exported HTML analysis reports. |
| `pgdata/` | PostgreSQL data volume for the Docker container (gitignored). |

It also holds runtime files created by the app: `history.sqlite` (conversation
history), `context.md` (generated schema summary), `sample.db` (SQLite demo DB),
and `logs/` (rotating app logs).

## Downloading sample data — no account needed

`download_public.bat` pulls retail datasets from public GitHub-hosted CSVs with
**no account or API key**. Stdlib only, so it works even before `setup.bat`.

```
download_public.bat          REM Superstore, Global Superstore, Superstore Orders
download_public.bat --list   REM show the source URLs
download_public.bat name https://.../file.csv   REM add an ad-hoc CSV
```

Files land in `data/raw/public/`. Then load with `load_data.bat data\raw`.

## Downloading sample data from Kaggle (needs a free Kaggle token)

`download_data.bat` pulls well-known retail / e-commerce datasets as CSV into
`data/raw/<dataset>/`. It needs Kaggle API credentials — either env vars
`KAGGLE_USERNAME` / `KAGGLE_KEY`, or a token file at
`%USERPROFILE%\.kaggle\kaggle.json` (Kaggle → Settings → "Create New Token").

```
download_data.bat            REM curated retail set (Superstore, Online Retail, Olist, ...)
download_data.bat --list     REM show the curated datasets
download_data.bat owner/dataset   REM a specific Kaggle dataset
```

## Loading CSVs into PostgreSQL

1. Start the database: `run_postgres.bat` (from the project root).
2. Put CSV files anywhere under a folder, e.g. `data/raw/sales/`.
   Each `*.csv` becomes a table named after the file (subfolder name is
   prefixed when needed to avoid collisions, e.g. `sales_orders`).
3. Load them: `load_data.bat data\raw`
   This **wipes** the target database, then recreates a table per CSV.
