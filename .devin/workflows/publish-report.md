---
description: Publish a Matrix G2 performance report to the public GitHub Pages site (sanitized)
---

Use this to safely publish a report from `results/` to the public `site/` reports hub.
Full details in `docs/PUBLISHING.md`.

1. Identify the results directory to publish (must contain `report.html`), e.g.
   `results/<run>/all_OR1_<timestamp>`.

2. Publish it (sanitizes HTML, regenerates sanitized PDF, extracts metadata, rebuilds the hub):
```
python -m tools.publish_report results/<run>/<report_dir> --title "<short title>"
```

3. Verify NOTHING sensitive leaked before pushing. The IP scan must return no matches:
```
Select-String -Path site\reports\*\report.html -Pattern "\b(\d{1,3}\.){3}\d{1,3}\b"
Get-ChildItem -Recurse site -Include *.csv,.env -ErrorAction SilentlyContinue
```

4. Open `site/index.html` in a browser and click through the report + PDF to confirm formatting.

5. Commit & push `site/` to the `gh-pages` branch (see docs/PUBLISHING.md for first-time setup):
```
cd site
git add .
git commit -m "Publish <report>"
git push
```
The `site/` folder has its own git repo tracking the `gh-pages` branch of the reports repo;
`main` (source) and `gh-pages` (reports) are pushed separately.
