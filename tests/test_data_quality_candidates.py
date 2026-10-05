"""Phase S (TRIAL_LIFECYCLE_BRIEF.md): the Data quality candidate finder was
rewritten so it no longer re-filters the whole Checks table for every row (it
ran on every page load, only to decide the Administration menu badge, and cost
about 95% of every tap's server time). The rewrite must return exactly what
the old function returned, so these tests compare the two directly: hand-made
cases, 250 randomised datasets, a scaling check, and the cache key."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_COMMON = """
    import sys, json, random, time
    sys.path.insert(0, "tests")
    import app, pandas as pd
    from reference_data_quality_candidates import reference_find_data_quality_candidates

    def reference(data, minutes=app.DATA_QUALITY_ISOLATION_WINDOW_MINUTES):
        return reference_find_data_quality_candidates(data, minutes, app.parse_dt, app.data_quality_reviewed_check_ids)

    def norm(value):
        if value is None:
            return None
        if isinstance(value, float) and value != value:
            return "NaN"
        if value is pd.NaT:
            return "NaT"
        if isinstance(value, pd.Timestamp):
            return ["Timestamp", value.isoformat()]
        return value

    def norm_list(items):
        return [{k: norm(v) for k, v in item.items()} for item in items]

    def make_checks(rows):
        out = []
        for check_id, trap_id, check_time, extra in rows:
            r = {c: "" for c in app.SHEETS["Checks"]}
            r.update({"Check ID": check_id, "Visit ID": "V", "Trap ID": trap_id, "Check Time": check_time, "Finding": "f"})
            r.update(extra)
            out.append(r)
        return pd.DataFrame(out, columns=app.SHEETS["Checks"])
"""


def _run(script: str) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(ROOT / "local_test_data_phase_s_unused"),
        }
    )
    env["R1M1_DATA_DIR"] = __import__("tempfile").mkdtemp()
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_COMMON) + textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_hand_made_cases_match_the_old_function_including_its_quirks() -> None:
    out = _run(
        """
        d = app.create_sample_data()
        t0, t1 = d["Traps"].iloc[0]["Trap ID"], d["Traps"].iloc[1]["Trap ID"]
        other_site_trap = d["Traps"][d["Traps"]["Site ID"] != d["Traps"].iloc[0]["Site ID"]].iloc[0]["Trap ID"]
        d["Audit Log"] = pd.DataFrame(
            [["CHG-1", "2026-09-01 00:00:00", app.DATA_QUALITY_REVIEW_RECORD_TYPE, "REV", "Status", "", "", "r"]],
            columns=app.SHEETS["Audit Log"],
        )
        cases = {
            "isolated pair 3h apart": [("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-01 11:00:00", {})],
            "pair inside window": [("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-01 08:30:00", {})],
            "exactly at the window edge": [("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-01 09:30:00", {})],
            "one second past the window": [("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-01 09:30:01", {})],
            "identical timestamps (gap 0)": [("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-01 08:00:00", {})],
            "unparseable time": [("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "garbage", {}), ("C", t0, "2026-09-01 08:10:00", {})],
            "blank time": [("A", t0, "", {}), ("B", t1, "2026-09-01 08:00:00", {})],
            "all times blank": [("A", t0, "", {}), ("B", t1, "", {})],
            "trap not in Traps": [("A", "NOPE-1", "2026-09-01 08:00:00", {}), ("B", t0, "2026-09-01 08:00:00", {})],
            "excluded check still a neighbour": [("A", t0, "2026-09-01 08:00:00", {"Excluded": "Yes"}), ("B", t1, "2026-09-01 08:20:00", {})],
            "excluded check is skipped": [("A", t0, "2026-09-01 08:00:00", {"Excluded": "Yes"}), ("B", t1, "2026-09-05 08:00:00", {})],
            "already reviewed": [("REV", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-05 08:00:00", {})],
            "two sites": [("A", t0, "2026-09-01 08:00:00", {}), ("B", other_site_trap, "2026-09-01 08:05:00", {})],
            "duplicate check ids": [("A", t0, "2026-09-01 08:00:00", {}), ("A", t1, "2026-09-01 08:10:00", {}), ("B", t0, "2026-09-03 08:00:00", {})],
            "single check": [("A", t0, "2026-09-01 08:00:00", {})],
            "other time formats": [("A", t0, "2026-09-01T08:00:00", {}), ("B", t1, "2026-09-01 08:00", {}), ("C", t0, "2026-09-09", {})],
            "unsorted input": [("C", t0, "2026-09-03 08:00:00", {}), ("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-02 08:00:00", {})],
        }
        mismatches = []
        results = {}
        for name, rows in cases.items():
            d["Checks"] = make_checks(rows)
            old, new = norm_list(reference(d)), norm_list(app.find_data_quality_candidates(d))
            results[name] = [(c["Check ID"], c["Site ID"]) for c in new]
            if old != new:
                mismatches.append({"case": name, "old": old, "new": new})
        d["Checks"] = make_checks([])
        empty_ok = app.find_data_quality_candidates(d) == [] == reference(d)
        print(json.dumps({"mismatches": mismatches, "results": results, "empty_ok": empty_ok}))
        """
    )
    assert out["mismatches"] == [], f"rewrite differs from the old function: {out['mismatches']}"
    assert out["empty_ok"] is True
    results = out["results"]
    # Documented behaviours of today's function, which the rewrite deliberately keeps:
    assert [c[0] for c in results["identical timestamps (gap 0)"]] == [], "a second check at the same instant is real activity nearby"
    assert "B" in [c[0] for c in results["unparseable time"]], "a check with an unparseable time is flagged today, not skipped"
    assert "A" in [c[0] for c in results["trap not in Traps"]], "a check on a trap missing from Traps is flagged today, not skipped"
    assert [c[0] for c in results["excluded check is skipped"]] == ["B"]
    assert "REV" not in [c[0] for c in results["already reviewed"]]


def test_randomised_datasets_match_the_old_function_exactly() -> None:
    out = _run(
        """
        random.seed(20261005)
        base_traps = app.create_sample_data()["Traps"]
        trap_ids = base_traps["Trap ID"].tolist()
        time_forms = [
            lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"),
            lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"),
            lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"),
            lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S"),
            lambda dt: dt.strftime("%Y-%m-%d %H:%M"),
            lambda dt: dt.strftime("%Y-%m-%d"),
            lambda dt: "garbage",
            lambda dt: "",
        ]
        mismatches, flagged_total, datasets = [], 0, 250
        for n in range(datasets):
            d = app.create_sample_data()
            if random.random() < 0.3:
                d["Traps"].at[random.randrange(len(d["Traps"])), "Site ID"] = ""
            rows = []
            count = random.choice([0, 1, 2, 3, 5, 8, 15, 30, 60])
            ids = []
            for i in range(count):
                check_id = random.choice(ids) if ids and random.random() < 0.08 else f"C{n}-{i}"
                ids.append(check_id)
                trap = "NOPE-9" if random.random() < 0.05 else random.choice(trap_ids)
                moment = pd.Timestamp("2026-09-01 06:00:00") + pd.Timedelta(minutes=random.choice([0, 5, 30, 61, 89, 90, 91, 200, 600, 1440, 4000]) + random.randint(0, 30) * random.choice([0, 1, 60]))
                if rows and random.random() < 0.1:
                    moment = pd.Timestamp(rows[-1][2][:19]) if rows[-1][2][:4] == "2026" and len(rows[-1][2]) >= 19 else moment
                formatted = random.choice(time_forms)(moment.to_pydatetime())
                extra = {"Excluded": "Yes"} if random.random() < 0.1 else {}
                rows.append((check_id, trap, formatted, extra))
            d["Checks"] = make_checks(rows)
            reviewed = [r[0] for r in rows if random.random() < 0.1]
            d["Audit Log"] = pd.DataFrame(
                [[f"CHG-{n}-{j}", "2026-09-01 00:00:00", app.DATA_QUALITY_REVIEW_RECORD_TYPE, rid, "Status", "", "", "r"] for j, rid in enumerate(reviewed)],
                columns=app.SHEETS["Audit Log"],
            )
            minutes = random.choice([0, 30, 90, 90, 90, 1000])
            old = norm_list(reference(d, minutes))
            new = norm_list(app.find_data_quality_candidates(d, minutes))
            flagged_total += len(old)
            if old != new:
                mismatches.append({"dataset": n, "minutes": minutes, "old": old, "new": new})
        print(json.dumps({"datasets": datasets, "flagged_total": flagged_total, "mismatches": mismatches[:3], "mismatch_count": len(mismatches)}))
        """
    )
    assert out["datasets"] >= 200
    assert out["flagged_total"] > 100, "the generator must actually produce candidates, or the comparison proves nothing"
    assert out["mismatch_count"] == 0, f"{out['mismatch_count']} datasets differ, e.g. {out['mismatches']}"


def test_cost_grows_roughly_linearly_not_with_the_square_of_the_rows() -> None:
    out = _run(
        """
        d = app.create_sample_data()
        traps = d["Traps"]["Trap ID"].tolist()
        def dataset(n):
            rows = [(f"C{i}", traps[i % len(traps)], (pd.Timestamp("2026-09-01 06:00:00") + pd.Timedelta(minutes=(i * 37) % 40000)).strftime("%Y-%m-%d %H:%M:%S"), {}) for i in range(n)]
            d["Checks"] = make_checks(rows)
            return d
        def best(fn, repeats=3):
            times = []
            for _ in range(repeats):
                start = time.perf_counter(); fn(); times.append(time.perf_counter() - start)
            return min(times)
        small = dataset(500); t_small = best(lambda: app.find_data_quality_candidates(small))
        large = dataset(2000); t_large = best(lambda: app.find_data_quality_candidates(large))
        t_old = best(lambda: reference(large), repeats=1)
        print(json.dumps({"small_s": t_small, "large_s": t_large, "ratio": t_large / t_small, "old_s": t_old}))
        """
    )
    # 4x the rows should cost about 4x, not 16x.
    assert out["ratio"] < 8, f"cost grew {out['ratio']:.1f}x for 4x the rows (small {out['small_s']:.3f}s, large {out['large_s']:.3f}s)"
    # And it must stay far cheaper than the per-row-rescan version it replaced
    # (measured about 40x cheaper at this size) - a relative check, no fixed
    # millisecond threshold. Code that goes back to rescanning per row fails it.
    assert out["large_s"] * 10 < out["old_s"], f"new {out['large_s']:.3f}s vs old {out['old_s']:.3f}s at 2,000 checks"


def test_badge_count_is_cached_on_the_workbook_mtime_not_on_the_data() -> None:
    out = _run(
        """
        d = app.create_sample_data()
        t0, t1 = d["Traps"].iloc[0]["Trap ID"], d["Traps"].iloc[1]["Trap ID"]
        two_flagged = make_checks([("A", t0, "2026-09-01 08:00:00", {}), ("B", t1, "2026-09-01 11:00:00", {})])
        none_flagged = make_checks([])
        d["Checks"] = two_flagged
        first = app.data_quality_candidate_count(1.0, d)
        d["Checks"] = none_flagged
        same_mtime = app.data_quality_candidate_count(1.0, d)   # served from the cache
        new_mtime = app.data_quality_candidate_count(2.0, d)    # a save happened: recomputed
        print(json.dumps({"first": first, "same_mtime": same_mtime, "new_mtime": new_mtime}))
        """
    )
    assert out == {"first": 2, "same_mtime": 2, "new_mtime": 0}
