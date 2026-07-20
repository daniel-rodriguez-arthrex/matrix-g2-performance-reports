
# Matrix G2 Performance Test Suite: 

Link to Report: https://daniel-rodriguez-arthrex.github.io/matrix-g2-performance-reports/

Standalone Python + Playwright performance testing and API discovery tool for Matrix G2 workflows.

## Modes

- **Passive monitoring**: Launch a headed browser, manually navigate Matrix G2, and capture all network traffic + timings.
- **Automated workflows**: Run scripted workflows (routing, presets, camera, etc.) and measure API + UI performance.

## Quick Start

1. Install Python 3.10+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```
3. Copy `.env.example` to `.env` and fill in real values:
   ```bash
   cp .env.example .env
   ```
   Room credentials, passcodes, and internal IPs are **only** read from `.env`
   (never hardcoded in source). Set `MATRIX_ROOMS_JSON` for multi-room, or the
   single-room `MATRIX_BASE_URL`/`MATRIX_USERNAME`/`MATRIX_PASSWORD` vars. `.env`
   is gitignored — do not commit it.
4. Run passive monitoring:
   ```bash
   python run_perf.py --mode passive --room OR1
   ```
5. Run an automated workflow:
   ```bash
   python run_perf.py --scenario routing --room OR1 --headless
   ```

## Output

Reports are written to `results/`:
- `api_calls.csv` — captured network requests
- `endpoints.csv` — discovered unique endpoints
- `selectors.csv` — selector validation results
- `ui_timings.csv` — UI render timings
- `summary.csv` — aggregate statistics
- `websocket_frames.csv` — captured WebSocket frames
- `report.html` — interactive dashboard

## Commands

```bash
# Passive monitoring (headed browser, manual navigation)
python run_perf.py --mode passive --room OR1

# Automated workflow (headless)
python run_perf.py --mode scenario --scenario routing --room OR1 --headless

# Run multiple iterations
python run_perf.py --scenario routing --room OR1 --headless --iterations 10

# Run all workflows
python run_perf.py --mode scenario --scenario all --room OR1 --headless

# Enforce API performance budget
python run_perf.py --scenario routing --room OR1 --headless --api-threshold 500

# Selector inspector (interactive click-to-pick)
python tools/selector_inspector.py --room OR1

# Validate a single selector
python tools/selector_inspector.py --room OR1 --selector "[data-testid='source-thumbnail']"

# Export a report to PDF (landscape, auto-scaled to avoid clipping)
python tools/html_to_pdf.py results/<run>/report.html

# Publish a sanitized report to the public GitHub Pages site
python -m tools.publish_report results/<run>/<report_dir> --title "Full Suite - OR1"
```

## Publishing reports (GitHub Pages)

Reports can be hosted publicly with all internal IPs/credentials sanitized. The
publish pipeline builds a separate `site/` repo (gitignored from source) containing
only sanitized `report.html` / `report.pdf` + a hub `index.html`. Raw CSVs (which
contain response bodies/tokens) are never published.

See **`docs/PUBLISHING.md`** for the full security model and step-by-step deployment.
