# Publishing Performance Reports to GitHub Pages

This guide explains how to publish Matrix G2 performance reports to a public GitHub
Pages site (mirroring the ORC reports model) **without exposing any sensitive data**.

## Security model

One public repo, two branches (mirrors the ORC model):

| Branch | Contents | Served by Pages? |
|--------|----------|------------------|
| `main` | Source code + workflows. Secrets only in a gitignored `.env`. Internal API-discovery docs are gitignored (local-only). | No |
| `gh-pages` (orphan) | Only sanitized `index.html` + `reports/<slug>/report.html` / `report.pdf` / `meta.json` (pushed from the `site/` folder). | **Yes** |

Serving Pages from an orphan `gh-pages` branch means the public site contains **only**
the sanitized hub + reports - source code and internal docs are never published, even
though they live on `main`.

Guardrails already in place:

- **No secrets in source.** `config/environments.py` reads all credentials, passcodes,
  and internal IPs from the environment (`.env`, which is gitignored). See `.env.example`.
- **Internal docs are gitignored** (`docs/discovered_*`, `docs/unique_api_endpoints.txt`,
  `docs/QUICK_REFERENCE.md`, `docs/WORKFLOW_UPDATE_SUMMARY.md`) so internal API details
  never reach the public `main` branch.
- **`site/` is gitignored** from `main`; its contents are pushed to `gh-pages` only.
- **Sanitization on publish.** `tools/sanitize_report.py` masks internal IPv4 addresses
  (and any URL-embedded credentials) as `[internal-host]` before a report is published.
- **PDF is regenerated from the sanitized HTML**, so it matches the redacted report.
- **Raw run artifacts are never published.** Only `report.html`, `report.pdf`, and a small
  `meta.json` are copied to `site/`. The CSVs (which contain full response bodies/tokens)
  stay in `results/` (also gitignored). `site/.gitignore` is a second defensive layer.

> Note: device friendly names (e.g. "Display 240 - 1") and device IDs
> (e.g. `mna-240-9730064510_dpOut0`) are intentionally **kept** in published reports.
> If that changes, extend `tools/sanitize_report.py`.

## Step 1 - Run a scenario (produces a report under `results/`)

```powershell
python run_perf.py --mode scenario --scenario all --room OR1 --headless --iterations 1 --api-threshold 500 --output-dir results\my_run
```

## Step 2 - Publish it into `site/` (sanitized)

```powershell
python -m tools.publish_report results\my_run\all_OR1_<timestamp> --title "Full Suite - OR1"
```

This will:
1. Sanitize `report.html` (prints how many IP references were masked).
2. Regenerate a sanitized `report.pdf`.
3. Extract metadata into `meta.json`.
4. Rebuild `site/index.html` (the hub) listing every published report.

Repeat Step 2 for each report you want on the site; the hub always reflects all of them.

## Step 3 - Verify before pushing (important)

```powershell
# Should return NOTHING. If it prints matches, do NOT push - re-run sanitization.
Select-String -Path site\reports\*\report.html -Pattern "\b(\d{1,3}\.){3}\d{1,3}\b"

# Confirm no raw data slipped in
Get-ChildItem -Recurse site -Include *.csv,.env
```

Open `site/index.html` in a browser and click through a report + PDF to confirm formatting.

## Step 4 - Publish the source (`main` branch, first time)

Run the pre-public secret scan first (see checklist below), then:

```powershell
git init
git add .
git commit -m "Matrix G2 performance test suite"
git branch -M main
git remote add origin https://github.com/<you>/matrix-g2-performance-reports.git
git push -u origin main
```

Gitignored files (`.env`, `results/`, `site/`, internal `docs/*`) are automatically
excluded.

## Step 5 - Publish the reports (`gh-pages` branch, first time)

The `site/` folder is gitignored from `main`, so give it its own git repo that pushes
to the `gh-pages` branch of the same remote:

```powershell
cd site
git init
git checkout -b gh-pages
git add .
git commit -m "Publish Matrix G2 performance reports"
git remote add origin https://github.com/<you>/matrix-g2-performance-reports.git
git push -u origin gh-pages
```

Then in the GitHub repo: **Settings -> Pages -> Build and deployment -> Source: Deploy
from a branch -> Branch: `gh-pages` / `(root)`**. The site will be served at
`https://<you>.github.io/matrix-g2-performance-reports/`.

## Step 6 - Publish updates later

```powershell
# add/refresh a report in site/
python -m tools.publish_report results\<new_run> --title "..."
# push it to gh-pages
cd site
git add .
git commit -m "Add <new report>"
git push
```

## Pre-publish checklist

- [ ] `git status` shows `.env`, `results/`, `site/`, and internal `docs/*` as ignored/untracked.
- [ ] Full IP scan on tracked files returns nothing (see command below).
- [ ] `Select-String` IP scan on `site/reports/*/report.html` returns nothing.
- [ ] No `*.csv` / `.env` files anywhere under `site/`.
- [ ] Hub `index.html` and each report render correctly in the browser.

```powershell
# Scan everything git WOULD track for leftover internal IPs (should print nothing)
git ls-files | ForEach-Object { Select-String -Path $_ -Pattern "\b(\d{1,3}\.){3}\d{1,3}\b" }
```
