# R1/M1 automated release gate

## What it checks

The release gate has two layers.

### Static and workbook checks

- Python syntax
- banned regressions such as embedded camera and old route wording
- required mobile and navigation safeguards
- clean seed row counts
- duplicate IDs
- broken workbook references
- one open window per trap
- spreadsheet formula errors

### Live browser checks

Against the Render staging app, Playwright checks:

- login at 390 px, 430 px and desktop widths
- horizontal overflow
- mobile sidebar toggle visibility
- site and first-trap journey shell
- user-facing trap terminology
- no embedded camera when Dead animal found is selected
- Add photo action present
- radio controls are not solid black
- screenshots at key states

## Local setup

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-test.txt
playwright install chromium
```

Run static checks:

```bash
python tests/release_gate.py
```

Run the full gate:

```bash
export R1M1_TEST_URL="https://your-app.onrender.com"
export R1M1_TEST_PASSWORD="your-staging-password"
./run_release_gate.sh
```

Credentials are read from environment variables and must not be committed.

## GitHub Actions

Add these repository secrets:

- `R1M1_TEST_URL`
- `R1M1_TEST_PASSWORD`

The workflow runs on pushes to `main` and can also be started manually.

Screenshots are uploaded as a GitHub Actions artifact after each run.

## Physical device checks still required

Browser automation cannot guarantee the exact native picker behaviour on a physical iPhone. Before field release, manually confirm:

- login does not zoom
- both sidebar chevrons are visible
- Add photo opens the expected device picker
- thumbnails appear
- images persist after save
- Safari bottom chrome does not cover controls


## Current staging values

Use these as repository secrets, not committed files:

- `R1M1_TEST_URL`: `https://r1m1-field-trial.onrender.com/`
- `R1M1_TEST_PASSWORD`: the current staging password

In GitHub: **Settings → Secrets and variables → Actions → New repository secret**.

After adding both secrets, open **Actions → R1M1 release gate → Run workflow**.


## v8.6.46 GitHub compatibility

The release gate uses `openpyxl` for workbook checks. The previous `artifact-tool`
dependency was removed because it is not published on public pip.


## v8.6.47 login selector

The browser test targets the exact password textbox role and name, avoiding
Streamlit's separate **Show password** button.
