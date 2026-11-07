# `input_data/` — your CSV files

Drop CSV files here and load them into PostgreSQL with:

```bat
load_data.bat input_data
```

Each `*.csv` becomes a table named after the file. Column names are normalised
to lowercase snake_case (`Order Date` → `order_date`). The target database is
**wiped first** unless you pass `--keep`.

The CSVs themselves are not committed — sample datasets belong to their
publishers and are downloaded, not redistributed.

## Getting sample data

| Option | Command | Needs |
|---|---|---|
| Public Superstore datasets | `download_public.bat` → `data\raw\public\` | Nothing |
| Curated Kaggle retail datasets | `download_data.bat` → `data\raw\<dataset>\` | Free Kaggle API token |
| Any CSV you already have | copy it here | — |

Load downloaded files with `load_data.bat data\raw`.

## Data used in the README screenshots

The screenshots were taken against four Walmart retail tables:

| File | Columns | Source |
|---|---|---|
| `walmart_sales.csv` | Store, Date, Weekly_Sales, Holiday_Flag, Temperature, Fuel_Price, CPI, Unemployment | Kaggle "Walmart sales" datasets |
| `sales_by_department.csv` | Store, Dept, Date, Weekly_Sales, IsHoliday | Kaggle — *Walmart Recruiting: Store Sales Forecasting* (`train.csv`) |
| `stores.csv` | Store, Type, Size | same competition (`stores.csv`) |
| `features.csv` | Store, Date, Temperature, Fuel_Price, MarkDown1-5, CPI, Unemployment, IsHoliday | same competition (`features.csv`) |

Competition data is available to anyone who accepts the competition rules on
Kaggle; download it there and place the files in this folder. Any other
tabular CSV works just as well — the app introspects whatever schema it finds.
