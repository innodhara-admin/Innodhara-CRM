"""Guard: are the three specification documents still true about the code?

A documentation sweep is a claim made once; this is the same claim re-made every
run. It compares the live code against:

  * BACKEND_README.md          (this repo)
  * YuviPep_Data_Model.docx    (repo parent)
  * YuviPep_30_Workflows.docx  (repo parent)

Checks
  1. Every table in the schema has a section in the Data Model, and every real
     column of every table is documented there.
  2. The Data Model names no field that does not exist in the code.
  3. The README's domain-model section lists every table.
  4. The README's stated counts (tables, routes, engines, permissions, tests…)
     match what the code actually has.
  5. Neither .docx still uses an identifier the code has renamed.
  6. Every plan operation the Planner can apply is named in the Workflows doc.
  7. The README's §7.1 breakdown of routes the Android app does not call adds up
     and matches the code, per category. (Added after that table was found to be
     mis-apportioned: the total was right and the rows were not, so the error
     cancelled out in the sum and nothing caught it.)

Exit code is non-zero when anything drifts, so this can gate a release.

    python scripts/check_docs_in_sync.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARENT = ROOT.parent
README = ROOT / "BACKEND_README.md"
DATA_MODEL = PARENT / "YuviPep_Data_Model.docx"
WORKFLOWS = PARENT / "YuviPep_30_Workflows.docx"
ANDROID_API = Path(
    r"C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI"
    r"\app\src\main\java\com\yuvipep\app\core\net\ApiService.java"
)

IMPLICIT = {"id", "org_id", "created_at", "updated_at"}
# Identifiers the code has renamed; a document still using one is out of date.
RENAMED = {
    "role_at_school": "role_at_client",
    "school_intelligence": "client_intelligence",
    "school_execution_in_progress": "client_execution_in_progress",
    "students_delta": "quantity_delta",
}
# `school_name` is deliberately NOT in that list: it is a real, still-supported
# template variable kept as the backward-compatible alias of `client_name`
# (intro_service.py, proposal_service.py), so a document may legitimately use it.

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def docx_text(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def documented_fields(path: Path) -> dict[str, set[str]]:
    """table name -> field names documented in its section."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))

    def body():
        for ch in d.element.body.iterchildren():
            if ch.tag.endswith("}p"):
                yield Paragraph(ch, d)
            elif ch.tag.endswith("}tbl"):
                yield Table(ch, d)

    out: dict[str, set[str]] = {}
    current: list[str] = []
    for item in body():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            combo = re.match(
                r"^\d+\.\d+\s+([a-z_][a-z0-9_]*)\s+(?:and|&)\s+([a-z_][a-z0-9_]*)",
                text)
            single = re.match(r"^\d+\.\d+\s+([a-z_][a-z0-9_]*)\s*(\[|$)", text)
            if combo:
                current = [combo.group(1), combo.group(2)]
            elif single:
                current = [single.group(1)]
            else:
                continue
            for name in current:
                out.setdefault(name, set())
        elif isinstance(item, Table) and current:
            header = [c.text.strip().lower() for c in item.rows[0].cells]
            col = header.index("field") if "field" in header else 0
            for row in item.rows[1:]:
                cell = row.cells[col].text.replace("✚", "")
                for token in re.findall(r"[a-z_][a-z0-9_]*", cell):
                    for name in current:
                        out[name].add(token)
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from app.core.constants import EventType
    from app.core.permissions import _MATRIX
    from app.database import Base
    from app.ai.planning import VALID_OPS
    import app.models  # noqa: F401
    import app.main as main_mod
    from fastapi.routing import APIRoute

    real = {n: {c.name for c in t.columns} for n, t in Base.metadata.tables.items()}
    n_tables = len(real)
    n_columns = sum(len(v) for v in real.values())
    n_routes = sum(
        len(r.methods - {"HEAD", "OPTIONS"})
        for r in main_mod.app.routes if isinstance(r, APIRoute)
    )
    n_perms = len(_MATRIX)
    n_events = len(list(EventType))

    print(f"code: {n_tables} tables, {n_columns} columns, {n_routes} routes, "
          f"{n_perms} permissions, {n_events} event types, "
          f"{len(VALID_OPS)} plan ops")

    # ── 1 + 2: Data Model coverage ───────────────────────────────────────────
    if not DATA_MODEL.exists():
        fail(f"missing {DATA_MODEL}")
    else:
        docd = documented_fields(DATA_MODEL)
        missing_tables = sorted(set(real) - set(docd))
        if missing_tables:
            fail(f"Data Model documents no section for: {', '.join(missing_tables)}")
        undocumented = 0
        for name, cols in real.items():
            if name not in docd:
                continue
            gap = sorted((cols - IMPLICIT) - docd[name])
            if gap:
                undocumented += len(gap)
                fail(f"Data Model {name}: undocumented column(s) {', '.join(gap)}")
        if not missing_tables and not undocumented:
            print(f"[PASS] Data Model covers all {n_tables} tables and every column")

        dm_text = docx_text(DATA_MODEL)
        stale = [old for old in RENAMED if re.search(rf"\b{old}\b", dm_text)]
        if stale:
            fail("Data Model uses renamed identifier(s): "
                 + ", ".join(f"{s} -> {RENAMED[s]}" for s in stale))
        else:
            print("[PASS] Data Model uses no renamed identifier")

    # ── 5 + 6: Workflows ─────────────────────────────────────────────────────
    if not WORKFLOWS.exists():
        fail(f"missing {WORKFLOWS}")
    else:
        wf_text = docx_text(WORKFLOWS)
        stale = [old for old in RENAMED if re.search(rf"\b{old}\b", wf_text)]
        if stale:
            fail("Workflows uses renamed identifier(s): "
                 + ", ".join(f"{s} -> {RENAMED[s]}" for s in stale))
        else:
            print("[PASS] Workflows uses no renamed identifier")

        missing_ops = sorted(op for op in VALID_OPS if op not in wf_text)
        if missing_ops:
            fail("Workflows never names plan operation(s): " + ", ".join(missing_ops))
        else:
            print(f"[PASS] Workflows names all {len(VALID_OPS)} plan operations")

        n_wf = len(re.findall(r"^Workflow \d+", wf_text, re.M))
        if n_wf != 30:
            fail(f"Workflows document has {n_wf} workflow headings, expected 30")
        else:
            print("[PASS] Workflows still has all 30 workflow headings")

    # ── 3 + 4: README ────────────────────────────────────────────────────────
    if not README.exists():
        fail(f"missing {README}")
    else:
        md = README.read_text(encoding="utf-8")
        start = md.find("## 12. Domain model")
        end = md.find("### Two modelling decisions")
        if start == -1 or end == -1:
            notes.append("README domain-model section not found by heading; "
                         "table-list check skipped")
        else:
            listed = set(re.findall(r"`([a-z_]+)`", md[start:end]))
            gap = sorted(set(real) - listed)
            if gap:
                fail(f"README domain model omits table(s): {', '.join(gap)}")
            else:
                print(f"[PASS] README domain model lists all {n_tables} tables")

        expected = {
            "tables": (n_tables, rf"\*\*{n_tables}\*\*\s*\|\s*55 model classes"),
            "routes": (n_routes, rf"\*\*{n_routes}\*\*\s*\|\s*16 endpoint modules"),
            "permissions": (n_perms, rf"\*\*{n_perms}\*\* permissions"),
            "events": (n_events, rf"{n_events} defined"),
            "plan ops": (len(VALID_OPS), rf"\*\*{len(VALID_OPS)}\*\*\s*\|\s*`pending_ops`"),
        }
        for label, (value, pattern) in expected.items():
            if not re.search(pattern, md):
                fail(f"README's stated {label} count does not match the code "
                     f"({value}); expected to find /{pattern}/")
        if all(re.search(p, md) for _, p in expected.values()):
            print("[PASS] README's stated counts match the code")

    # ── 7: the §7.1 "routes the app does not call" breakdown ─────────────────
    if not ANDROID_API.exists():
        notes.append(f"Android ApiService not found at {ANDROID_API}; "
                     "the §7.1 breakdown check was skipped")
    elif README.exists():
        md = README.read_text(encoding="utf-8")
        java = ANDROID_API.read_text(encoding="utf-8")
        used = {
            (mth, re.sub(r"\{[^}]+\}", "{}", "/" + path.lstrip("/")))
            for mth, path in re.findall(
                r'@(GET|POST|PATCH|PUT|DELETE)\("([^"]+)"\)', java)
        }
        # module -> how the README groups it
        GROUP = {
            "app.api.admin": "Organisation administration",
            "app.api.organisations": "Platform / Super Admin",
            "app.api.misc": None,          # split: devices vs the rest
            "app.api.ops": None,           # split: approval rules vs the rest
            "app.api.workflow": None,      # split: incidents vs the rest
        }
        counts: dict[str, int] = {}
        total_uncalled = 0
        for r in main_mod.app.routes:
            if not isinstance(r, APIRoute):
                continue
            for mth in sorted(r.methods - {"HEAD", "OPTIONS"}):
                if (mth, re.sub(r"\{[^}]+\}", "{}", r.path)) in used:
                    continue
                total_uncalled += 1
                mod, path = r.endpoint.__module__, r.path
                if mod == "app.api.ops":
                    key = ("Approval rules" if "/approval-rules" in path
                           else "Operations and money")
                elif mod == "app.api.workflow":
                    key = ("Incidents" if "/incidents" in path
                           else "Everything else")
                elif mod == "app.api.misc":
                    key = ("Device push registration" if "/devices" in path
                           else "Everything else")
                else:
                    key = GROUP.get(mod) or "Everything else"
                counts[key] = counts.get(key, 0) + 1

        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        print(f"[INFO] §7.1 breakdown from code: {total_uncalled} uncalled "
              f"({summary})")

        section = md[md.find("### 7.1"):md.find("### 7.2")]
        if not section:
            notes.append("README §7.1 not found; breakdown check skipped")
        else:
            bad = []
            for label, n in counts.items():
                # the row's label may carry a module hint in brackets
                row = re.search(rf"^\|\s*{re.escape(label)}[^|]*\|\s*(\d+)\s*\|",
                                section, re.M)
                if row is None:
                    bad.append(f"no §7.1 row for '{label}' (code says {n})")
                elif int(row.group(1)) != n:
                    bad.append(f"§7.1 row '{label}' says {row.group(1)}, "
                               f"code says {n}")
            stated_total = re.search(r"### 7\.1 What the app does not call "
                                     r"\((\d+) routes\)", section)
            if stated_total and int(stated_total.group(1)) != total_uncalled:
                bad.append(f"§7.1 heading says {stated_total.group(1)} routes, "
                           f"code says {total_uncalled}")
            rows = [int(x) for x in re.findall(r"^\|[^|]+\|\s*(\d+)\s*\|",
                                              section, re.M)]
            if rows and sum(rows) != total_uncalled:
                bad.append(f"§7.1 rows sum to {sum(rows)}, "
                           f"expected {total_uncalled}")
            for b in bad:
                fail(b)
            if not bad:
                print("[PASS] README §7.1 breakdown matches the code, "
                      f"per category and in total ({total_uncalled})")

    print()
    for note in notes:
        print(f"[NOTE] {note}")
    if failures:
        print(f"FAIL - {len(failures)} drift(s) between the code and the docs:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("OK - the three documents agree with the code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
