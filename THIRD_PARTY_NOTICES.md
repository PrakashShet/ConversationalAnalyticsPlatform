# Third-party notices

This project's own source code is released under the [MIT License](LICENSE).
It depends on, and in one case vendors, third-party software that is distributed
under its own license terms, summarised below. Those terms continue to apply to
the respective components.

## Vendored in this repository

| Component | Version | License | Location |
|---|---|---|---|
| [Apache ECharts](https://echarts.apache.org/) | 5.6.0 | Apache License 2.0 | `app/resources/vendor/echarts.min.js` |

ECharts is bundled so the interactive charts work offline (no CDN). Its
original license header is preserved at the top of the file. Full license text:
<https://www.apache.org/licenses/LICENSE-2.0>.

## Runtime dependencies (installed via `requirements.txt`, not vendored)

| Package | License |
|---|---|
| PySide6 / PySide6-Addons / shiboken6 (Qt for Python) | LGPL-3.0 (or commercial) |
| google-genai | Apache-2.0 |
| mcp | MIT |
| keyring | MIT |
| pydantic, pydantic-settings | MIT |
| platformdirs | MIT |
| loguru | MIT |
| python-dotenv | BSD-3-Clause |
| pandas, numpy | BSD-3-Clause |
| statsmodels | BSD-3-Clause |
| SQLAlchemy | MIT |
| psycopg2-binary | LGPL-3.0 (with exceptions) |
| kagglehub | Apache-2.0 |
| pytest | MIT |

**Distributing a frozen build.** The PyInstaller build (`run_build.bat`) bundles
Qt and PySide6, which are LGPL-licensed. The onedir layout keeps the Qt
libraries as separate, replaceable DLLs, which is what LGPL dynamic linking
expects. If you redistribute `dist/ConvAnalytics/`, include this notice and
make the LGPL license texts and the corresponding Qt/PySide6 source location
available to recipients.

## Sample data

No third-party datasets are committed to this repository. The download scripts
(`download_public.bat`, `download_data.bat`) fetch public retail datasets from
their original publishers; each dataset is governed by the terms of its source.
See [`input_data/README.md`](input_data/README.md).
