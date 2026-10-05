# Field speed Phase 1: handoff

Branch `feature/field-speed-phase1`, two commits on top of `main` (`fa4f665`):
`fba9f3d` (Part A, probe) and `d674856` (Part B, navigation). Nothing from the
parked bulk-trial branch is included.

All timings below are from a local test run on synthetic demo data (15 Windows
rows) on a laptop. They show the *number of script runs per tap*, which is what
Part B changes. They say nothing about phone or network time: that is Part D.

## Turning the probe on and off

- Off by default. Set the environment variable `SPEED_PROBE` to `1` on the Render
  service to turn it on; remove it to turn it off. No code change or URL parameter.
- On: one log line per script run in the Render logs, and a one-line caption at the
  bottom of each page.
- Log line: `SPEEDPROBE page=<page> kind=<complete|navigate|rerun> run_ms=<n> load_ms=<n> save_ms=<n> windows_rows=<n> cb_ms=<n>`
- Two additions to the brief's format:
  - `cb_ms`: time spent in the button's callback, which runs *before* the script starts
    (so it is not part of `run_ms`). `load_ms`/`save_ms` include any load/save done in
    that callback. Total server time for a tap = `run_ms` + `cb_ms`.
  - `kind=rerun`: a run cut short by a two-phase button's arming rerun (Save check uses
    one). The brief only named `complete` and `navigate`.
- Caption "server" = `run_ms` + `cb_ms`. "tap→render" is finger-down to the page settling,
  measured on the phone. A tap that lands before the previous caption has loaded is
  folded into the same sample, by design.
- Pages that stop early (`st.stop()`: the "Resume checking?" prompt, some error states)
  log no `complete` line and show no caption.

## Part B: before and after (raw logs)

Sequence: Start checking, Check, back, Check another, (reload on check page), back,
(reload on trap selector), Pause, Resume checking, Check, Exit to Trap sites.

### Before (commit `fba9f3d`, probe only)

```
--- start_checking: ['navigate', 'complete']
    SPEEDPROBE page=visit kind=navigate run_ms=87 load_ms=4 save_ms=32 windows_rows=15 cb_ms=0
    SPEEDPROBE page=visit kind=complete run_ms=86 load_ms=30 save_ms=0 windows_rows=15 cb_ms=0
--- check_trap_1: ['rerun', 'navigate', 'complete']
    SPEEDPROBE page=visit kind=rerun run_ms=58 load_ms=4 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=check kind=navigate run_ms=351 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=check kind=complete run_ms=46 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
--- back_to_selector: ['navigate', 'complete']
    SPEEDPROBE page=visit kind=navigate run_ms=51 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=visit kind=complete run_ms=48 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
--- check_another: ['rerun', 'navigate', 'complete']
    SPEEDPROBE page=visit kind=rerun run_ms=56 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=check kind=navigate run_ms=353 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=check kind=complete run_ms=47 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
_reload_on_check_page: resume_prompt
--- back_again: ['navigate', 'complete']
    SPEEDPROBE page=visit kind=navigate run_ms=58 load_ms=4 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=visit kind=complete run_ms=47 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
_reload_on_visit_page: trap_sites
--- pause: ['navigate', 'complete']
    SPEEDPROBE page=sites kind=navigate run_ms=60 load_ms=4 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=sites kind=complete run_ms=47 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
--- resume_checking: ['navigate', 'complete']
    SPEEDPROBE page=visit kind=navigate run_ms=60 load_ms=4 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=visit kind=complete run_ms=46 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
--- check_before_exit: ['rerun', 'navigate', 'complete']
    SPEEDPROBE page=visit kind=rerun run_ms=56 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=check kind=navigate run_ms=350 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=check kind=complete run_ms=46 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
--- exit_to_trap_sites: ['navigate', 'complete']
    SPEEDPROBE page=sites kind=navigate run_ms=44 load_ms=5 save_ms=0 windows_rows=15 cb_ms=0
    SPEEDPROBE page=sites kind=complete run_ms=46 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
_reload_on_trap_sites: trap_sites
```

### After (commit `d674856`)

```
--- start_checking: ['complete']
    SPEEDPROBE page=visit kind=complete run_ms=79 load_ms=122 save_ms=31 windows_rows=15 cb_ms=120
--- check_trap_1: ['complete']
    SPEEDPROBE page=check kind=complete run_ms=60 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
--- back_to_selector: ['complete']
    SPEEDPROBE page=visit kind=complete run_ms=62 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
--- check_another: ['complete']
    SPEEDPROBE page=check kind=complete run_ms=60 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
_reload_on_check_page: resume_prompt
--- back_again: ['complete']
    SPEEDPROBE page=visit kind=complete run_ms=64 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
_reload_on_visit_page: trap_sites
--- pause: ['complete']
    SPEEDPROBE page=sites kind=complete run_ms=59 load_ms=4 save_ms=0 windows_rows=15 cb_ms=0
--- resume_checking: ['complete']
    SPEEDPROBE page=visit kind=complete run_ms=64 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
--- check_before_exit: ['complete']
    SPEEDPROBE page=check kind=complete run_ms=47 load_ms=2 save_ms=0 windows_rows=15 cb_ms=0
--- exit_to_trap_sites: ['complete']
    SPEEDPROBE page=sites kind=complete run_ms=60 load_ms=3 save_ms=0 windows_rows=15 cb_ms=0
_reload_on_trap_sites: trap_sites
```

Reading it: every converted tap is one `complete` run. "Check" went from three runs
(`rerun`, `navigate`, `complete`; the old `navigate` run included a 0.3 s sleep) to one.
"Start checking" now does its save inside the callback: `cb_ms=120`, `save_ms=31`.
What a reload restores is identical before and after.

## Part B: every `go()` / `navigate()` / `set_page()` call site (line numbers on this branch)

| Line | What it is | Converted? | Why |
|---|---|---|---|
| 1599 | `go()` helper | n/a | Helper (`navigate(rerun=True)`); still used by every unconverted call below |
| 1604 | `set_page()` helper | n/a | Helper (`navigate(rerun=False)`); the callback route used by the converted buttons |
| 1621 | `start_checking_callback()` | new | Callback for Start checking: loads the workbook, creates the visit (saves), then `navigate(rerun=False)` |
| 2641 | `nav_go()` helper | no | Has no callers; left alone |
| 3196 | Trap card "Check" | **yes** | On the brief's list. The two-phase "Opening…" state is gone (it caused the extra runs) |
| 4930 | Resume prompt, "Resume" | no | Dropped-connection restore; the brief says it must behave exactly as before; not on the list |
| 4933 | Resume prompt, "Start over" | no | Same |
| 5123 | "← Exit to Trap sites" | **yes** | On the list |
| 5188 | Trap sites card "Resume checking" | **yes** | On the list |
| 5193 | Trap sites card "Start checking" | **yes** | On the list; save moved into the callback |
| 5202 | Site page, inactive-site "Back to Trap sites" | no | Not on the list; error branch that ends in `st.stop()` |
| 5205 | Site page "← Trap sites" | no | Pure navigation but not on the list (candidate for Phase 2) |
| 5215 | Site page "Start checking traps" | no | Not on the list. Same save-then-navigate pattern as Start checking (candidate for Phase 2) |
| 5230 | Start-visit page, inactive-site back button | no | Error branch |
| 5233 | Start-visit page automatic redirect | no | Not a button; runs inside the script |
| 5253 | Visit page, "visit not found" back button | no | Error branch |
| 5375 | "Finish site check" | no | Writes the visit in the same run; the brief says keep |
| 5376 | "Pause and return to Trap sites" | **yes** | On the list |
| 5389 | "Cancel check" | no | Writes (deletes the visit); the brief says keep |
| 5409 | "← Back to trap selector" | **yes** | On the list |
| 5806 | "Save check" | no | Validates, stages and writes in the same run; the brief says keep |
| 5894 | Traps list "View" | no | Administration page, not the field path; not on the list |
| 5909 | Trap detail "Back to traps" (not-found branch) | no | Error branch |
| 5925 | Trap detail "← Back to traps" | no | Administration page; not on the list |
| 6324 | Trial history "← Back to Data Management" | no | Administration page; not on the list |
| 6747 | Trap edit, not-found "Back to Trial setup" | no | Error branch |
| 6751 | Trap edit "← Back to Trial setup" | no | Administration page; not on the list |
| 6775 | Save trap changes | no | Writes in the same run |
| 6795 | Deactivate trap | no | Writes in the same run |
| 6815 | Activate trap | no | Writes in the same run |
| 6843 | Move trap | no | Writes in the same run |
| 6869 | Change build | no | Writes in the same run |
| 7014 | Trial setup "Edit" | no | Administration page; not on the list |
| 8006 | "Open trial history" | no | Administration page; not on the list |

## Part C: what could and could not be reported

From the repo (`render.yaml`, `.streamlit/config.toml`, `requirements.txt`):

- Plan `starter`, auto-deploy on, health check `/`, Python 3.12.3, Streamlit 1.60.0.
- Region: not set anywhere in the repo or docs. Needs a look at the Render dashboard
  (Settings, Region). A service's region cannot be changed after creation.
- Persistent disk: `r1m1-data`, 1 GB, mounted at `/var/data`. `R1M1_DATA_DIR=/var/data`,
  so the workbook, the `backups` folder (20 kept, a full copy on every save) and the
  evidence photos are all on the attached disk.
- Start command: `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT
  --server.headless true --server.disconnectedSessionTTL=900`. No other server flags.

Needs the running service (not reachable from the development machine):

- Workbook size on disk: Render Shell, `ls -l /var/data`.
- Row counts: Windows rows appear as `windows_rows` in the first probe log line once
  the probe is on. Checks, Followups and Audit Log: Data & records, then Export and
  backup, then Inspect data table.
- Memory at idle and after opening Trial performance: Render dashboard, Metrics tab,
  Memory graph. Note the time of each action.
- Confirm the instance type shown in the dashboard matches `starter`.
