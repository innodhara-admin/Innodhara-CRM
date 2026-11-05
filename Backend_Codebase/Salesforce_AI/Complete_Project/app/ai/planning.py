"""LLM-native planning — the generic brain of the Planner Engine.

Any transcript on any topic becomes a validated task breakdown (initial plan)
or a validated plan diff (merge). The LLM authors the WHAT (tasks, phases,
skills, dependencies, commitments, contradictions); deterministic code keeps
the HOW (versioning, approval gates, assignment scoring, pricing tables).

Design rules honoured here:
- Output is schema-constrained JSON, then re-validated field by field.
  Anything the model invents outside the allowed vocabulary is dropped or
  normalised — never silently trusted.
- Prices are NEVER taken from the model. Value estimates come from pricing
  tables only (planner_engine._estimate_value).
- If the model is unreachable after retries, callers hold the work for a
  human (PlanningUnavailable) — production never falls back to keyword
  templates; those exist only for the stub/test provider.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import AssignOn, Influence, Phase, TaskPriority
from app.core.exceptions import BudgetExceededError, ExternalServiceError

logger = logging.getLogger(__name__)

VALID_PHASES = {p.value for p in Phase}
VALID_PRIORITIES = {p.value for p in TaskPriority}
VALID_ASSIGN_ON = {a.value for a in AssignOn}
VALID_INFLUENCE = {i.value for i in Influence}
MAX_TASKS = 30

# Ops the Planner can apply at activation — the model may only speak this
# vocabulary; anything else is dropped during validation.
VALID_OPS = {
    "redate", "cancel", "reopen", "unblock", "set_window",
    "renegotiate_commitment",
    # A client asking to move the DEMO had no op to express it. `redate` moves a
    # TASK, so the model did the only thing it could: re-dated whatever task
    # mentioned the word "demo" while the demo itself kept its old date. The
    # reschedule machinery existed all along — behind the app's Reschedule
    # button — and a meeting could not reach it.
    "reschedule_demo",
}


class PlanningUnavailable(Exception):
    """The model could not produce a usable result — hold for a human."""


# ─────────────────────────────────────────────────────────────────────────────
# Org context gathering (facts the model plans WITH — never invents)
# ─────────────────────────────────────────────────────────────────────────────


async def org_skill_names(db: AsyncSession, org_id: str) -> list[str]:
    from app.models.user import UserSkill

    rows = (
        await db.execute(
            select(UserSkill.skill).where(UserSkill.org_id == org_id).distinct()
        )
    ).scalars().all()
    return sorted(rows)


async def _org_context(db: AsyncSession, org_id: str) -> dict[str, Any]:
    from app.models.program import Program

    programs = (
        await db.execute(
            select(Program).where(Program.org_id == org_id, Program.is_active.is_(True))
        )
    ).scalars().all()
    return {
        "programs": [
            {"name": p.name, "description": (p.description or "")[:200]}
            for p in programs
        ],
        "skills": await org_skill_names(db, org_id),
    }


def _context_block(ctx: dict[str, Any]) -> str:
    lines: list[str] = []
    if ctx.get("programs"):
        lines.append("Programs/offerings this organisation sells:")
        lines += [f"- {p['name']}: {p['description']}" for p in ctx["programs"]]
    else:
        lines.append("This organisation has no predefined program catalogue.")
    if ctx.get("skills"):
        lines.append(
            "\nSkills that exist in the team. Set required_skill to ONE of these "
            "EXACT names, and to 'general' when a task needs no particular "
            "specialism. Do NOT invent a new skill name — an invented name "
            "matches nobody, so the task falls back to the phase lead unassigned "
            "(finding F25):"
        )
        lines.append(", ".join(ctx["skills"]))
    else:
        lines.append(
            "\nNo skill taxonomy exists yet — use 'general' for required_skill, "
            "or a short snake_case name only when a clear specialism applies."
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Validation — the deterministic fence around model output
# ─────────────────────────────────────────────────────────────────────────────


def _norm_skill(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = re.sub(r"[^a-z0-9]+", "_", str(raw).strip().lower()).strip("_")
    return s[:100] or None


def norm_role(raw: str | None) -> str | None:
    """Free-form stakeholder role → snake_case, any client vocabulary
    ("Chief Technology Officer" → "chief_technology_officer"). There is no
    fixed role list — the vocabulary belongs to the client organisation."""
    if not raw or not str(raw).strip():
        return None
    s = re.sub(r"[^a-z0-9]+", "_", str(raw).strip().lower()).strip("_")
    return s[:50] or None  # column is String(50)


def _parse_iso_date(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def validate_task_specs(
    raw_tasks: Any, org_skills: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Model task list → clean planner task specs + list of skill gaps
    (skills nobody in the org holds)."""
    if not isinstance(raw_tasks, list):
        return [], []
    known = set(org_skills)
    specs: list[dict[str, Any]] = []
    titles_seen: set[str] = set()
    gaps: set[str] = set()
    for raw in raw_tasks[:MAX_TASKS]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()[:490]
        if not title or title.lower() in titles_seen:
            continue
        titles_seen.add(title.lower())
        skill = _norm_skill(raw.get("required_skill"))
        if skill and skill not in known:
            # The prompt is not a fence (F25, and the recurring lesson of this
            # job): if the model invents a skill outside the org's taxonomy it
            # would match nobody, so record the gap for reporting but coerce the
            # task onto 'general' (which everyone holds) — never leave it on a
            # phantom skill. When no taxonomy exists at all, keep the model's
            # word (bootstrap: an org that has never defined skills).
            gaps.add(skill)
            if known:
                skill = "general" if "general" in known else None
        due_days = raw.get("due_in_days")
        try:
            due_days = max(0, min(int(due_days), 365))
        except (TypeError, ValueError):
            due_days = 7
        spec: dict[str, Any] = {
            "title": title,
            "description": (str(raw.get("description") or "").strip() or None),
            "phase": raw.get("phase") if raw.get("phase") in VALID_PHASES
            else Phase.PREPARATION.value,
            "required_skill": skill,
            "due_in_days": due_days,
            "priority": raw.get("priority") if raw.get("priority") in VALID_PRIORITIES
            else TaskPriority.P2.value,
            "visible_to_client": bool(raw.get("visible_to_client", False)),
            "assign_on": raw.get("assign_on") if raw.get("assign_on") in VALID_ASSIGN_ON
            else AssignOn.PLAN_ACTIVATION.value,
            "depends_on": [
                str(d).strip() for d in (raw.get("depends_on") or [])
                if isinstance(d, str) and d.strip()
            ],
        }
        commitment = raw.get("commitment")
        if isinstance(commitment, dict) and str(commitment.get("text") or "").strip():
            c_days = commitment.get("due_in_days")
            try:
                c_days = max(0, min(int(c_days), 365))
            except (TypeError, ValueError):
                c_days = due_days
            spec["commitment"] = {
                "text": str(commitment["text"]).strip()[:490],
                "due_in_days": c_days,
                "direction": commitment.get("direction")
                if commitment.get("direction") in ("ours", "theirs") else "ours",
            }
        specs.append(spec)
    # Dependencies may only reference titles inside this batch.
    valid_titles = {s["title"] for s in specs}
    for s in specs:
        s["depends_on"] = [d for d in s["depends_on"] if d in valid_titles and d != s["title"]]
    return specs, sorted(gaps)


def validate_complaints(raw: Any) -> list[dict[str, Any]]:
    """Model complaint list → clean specs (F54).

    Deliberately conservative: a complaint raises an incident and pages BOTH
    leads at P1, so a false positive is expensive. Anything without real detail
    is dropped rather than escalated.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        detail = str(item.get("detail") or "").strip()[:1000]
        # A bare "unhappy" is not something a lead can act on at 2am.
        if len(detail) < 10 or detail.lower() in seen:
            continue
        seen.add(detail.lower())
        out.append({
            "detail": detail,
            "raised_by": (str(item.get("raised_by") or "").strip()[:200] or None),
        })
    return out


def validate_stakeholder_specs(raw: Any) -> list[dict[str, Any]]:
    """Model stakeholder list → clean specs. The role stays free-form
    (normalised snake_case, whatever the client organisation calls the
    person); influence is fenced to the fixed vocabulary and dropped when
    the model spoke outside it — the deterministic default then applies."""
    if not isinstance(raw, list):
        return []
    specs: list[dict[str, Any]] = []
    names_seen: set[str] = set()
    for item in raw[:10]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:200]
        if not name or name.lower() in names_seen:
            continue
        names_seen.add(name.lower())
        specs.append({
            "name": name,
            "role": norm_role(item.get("role")),
            "influence": item.get("influence")
            if item.get("influence") in VALID_INFLUENCE else None,
            "receives_updates": bool(item.get("receives_updates", False)),
            # F55: true = a real person at this client whose involvement is some
            # OTHER piece of business. The CONTACT is still created — they exist,
            # and [F41] is precisely about not throwing discovered people away —
            # but the project-scoped STAKEHOLDER row is not.
            "other_engagement": bool(item.get("other_engagement", False)),
        })
    return specs


def validate_ops(
    raw_ops: Any,
    *,
    known_task_ids: set[str],
    known_commitment_ids: set[str],
    known_demo_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Model plan-diff ops → only ops the activation code can actually apply,
    referencing only rows that actually exist."""
    if not isinstance(raw_ops, list):
        return []
    known_demo_ids = known_demo_ids or set()
    ops: list[dict[str, Any]] = []
    for raw in raw_ops[:50]:
        if not isinstance(raw, dict) or raw.get("op") not in VALID_OPS:
            continue
        kind = raw["op"]
        if kind == "set_window":
            start = _parse_iso_date(raw.get("start"))
            end = _parse_iso_date(raw.get("end"))
            if start is None and end is None:
                continue
            ops.append({
                "op": "set_window",
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            })
        elif kind == "reschedule_demo":
            # Only a demo the snapshot actually showed, and only with a real
            # date — a demo move sends the client an updated calendar invite,
            # so a hallucinated id or a vague "next week" must not get through.
            new_date = _parse_iso_date(raw.get("new_date"))
            if raw.get("demo_id") not in known_demo_ids or new_date is None:
                continue
            demo_op = {"op": kind, "demo_id": raw["demo_id"],
                       "new_date": new_date.date().isoformat()}
            t = str(raw.get("new_time") or "").strip()
            if re.fullmatch(r"\d{1,2}:\d{2}", t):
                demo_op["new_time"] = t
            ops.append(demo_op)
        elif kind == "renegotiate_commitment":
            new_due = _parse_iso_date(raw.get("new_due"))
            if raw.get("commitment_id") not in known_commitment_ids or new_due is None:
                continue
            ops.append({
                "op": kind, "commitment_id": raw["commitment_id"],
                "new_due": new_due.isoformat(),
            })
        else:
            if raw.get("task_id") not in known_task_ids:
                continue
            op: dict[str, Any] = {"op": kind, "task_id": raw["task_id"]}
            if kind in ("redate", "reopen"):
                new_due = _parse_iso_date(raw.get("new_due"))
                if kind == "redate" and new_due is None:
                    continue
                if new_due is not None:
                    op["new_due"] = new_due.isoformat()
                    op["old_due"] = str(raw.get("old_due") or new_due.isoformat())
            if raw.get("reason"):
                op["reason"] = str(raw["reason"])[:300]
            ops.append(op)
    return ops


# ─────────────────────────────────────────────────────────────────────────────
# Model call helper: one retry on malformed output, then hold for a human
# ─────────────────────────────────────────────────────────────────────────────


def repair_truncated_json(text: str) -> Any | None:
    """Structured output's only malformation mode is truncation (the token
    cap cut the reply mid-value). Drop the trailing partial element and close
    the open brackets — downstream field validators discard anything that
    lost meaning in the cut."""
    import json

    starts = [p for p in (text.find("{"), text.find("[")) if p != -1]
    if not starts:
        return None
    s = text[min(starts):].rstrip()
    for _ in range(300):
        stack: list[str] = []
        in_str = esc = False
        for ch in s:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]" and stack:
                stack.pop()
        candidate = (
            s + ('"' if in_str else "")
            + "".join("}" if b == "{" else "]" for b in reversed(stack))
        )
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        cut = max(s.rfind(","), s.rfind("{"), s.rfind("["))
        if cut <= 0:
            return None
        s = s[:cut].rstrip()
    return None


async def _ask(
    *,
    purpose: str,
    org_id: str,
    system: str,
    user_content: str,
    schema: dict[str, Any],
    required_keys: tuple[str, ...],
    tier: str = "strong",
    max_tokens: int = 32768,
) -> dict[str, Any]:
    from app.ai.llm import extract_json, get_model_layer

    last_error: str = "malformed model output"
    for attempt in range(2):
        try:
            content = user_content if attempt == 0 else (
                user_content
                + "\n\nIMPORTANT: your previous reply was not valid JSON matching "
                "the schema. Reply again with ONLY the JSON object, and keep it "
                "compact — no repetition."
            )
            response = await get_model_layer().generate(
                purpose=purpose,
                org_id=org_id,
                tier=tier,
                system=system,
                messages=[{"role": "user", "content": content}],
                json_schema=schema,
                temperature=0.2,
                max_tokens=max_tokens,
                # Cap reasoning so a long think can never starve the JSON
                # reply out of the output budget (verified live: uncapped
                # thinking truncated merge diffs mid-string).
                thinking_budget=min(8192, max_tokens // 2),
            )
            try:
                result = extract_json(response.text)
            except Exception:  # noqa: BLE001 — truncated reply: repair it
                result = repair_truncated_json(response.text)
                if result is not None:
                    logger.warning(
                        "planning %s: reply was truncated (%d chars); repaired",
                        purpose, len(response.text),
                    )
            if isinstance(result, dict) and all(k in result for k in required_keys):
                return result
            last_error = (
                f"unusable model reply (len={len(response.text)}, "
                f"tail={response.text[-200:]!r})"
            )
        except (ExternalServiceError, BudgetExceededError) as exc:
            # Retries/backoff already happened inside the model layer.
            raise PlanningUnavailable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if attempt == 0:
            logger.warning("planning %s attempt 1 failed: %s", purpose, last_error[:400])
    raise PlanningUnavailable(last_error)


_COMPLAINT_ITEM_SCHEMA: dict[str, Any] = {
    # F54: the meeting contract had NO field for a complaint, so the whole of
    # Workflow 22 was unreachable from a meeting — "your trainer arrived 40
    # minutes late", said to a rep's face, produced one task and nothing else,
    # while the same words by email paged both leads in seconds.
    "type": "object",
    "properties": {
        "detail": {"type": "string"},
        "raised_by": {"type": "string"},
    },
    "required": ["detail"],
}

_STAKEHOLDER_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "role": {"type": "string"},
        "influence": {"type": "string", "enum": sorted(VALID_INFLUENCE)},
        "receives_updates": {"type": "boolean"},
        # F55: the contract had no way to say "this person's involvement is a
        # DIFFERENT engagement", so a second campus's head named in passing was
        # bound to the project under discussion — as a decision_maker.
        "other_engagement": {"type": "boolean"},
    },
    "required": ["name", "role"],
}

_TASK_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "phase": {"type": "string", "enum": sorted(VALID_PHASES)},
        "required_skill": {"type": "string"},
        "due_in_days": {"type": "integer"},
        "priority": {"type": "string", "enum": sorted(VALID_PRIORITIES)},
        "visible_to_client": {"type": "boolean"},
        "assign_on": {"type": "string", "enum": sorted(VALID_ASSIGN_ON)},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "commitment": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "due_in_days": {"type": "integer"},
                "direction": {"type": "string", "enum": ["ours", "theirs"]},
            },
        },
    },
    "required": ["title", "phase", "required_skill", "due_in_days"],
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Initial plan — any first meeting on any topic → project + task breakdown
# ─────────────────────────────────────────────────────────────────────────────

_INITIAL_SYSTEM = """You are the planning engine of a services company's \
operations platform. A field agent met a client and recorded the discussion. \
You turn that discussion into the company's INTERNAL work plan.

Rules:
- Plan only work that follows from what was actually discussed. Never invent \
requirements, dates, or prices.
- concrete=false when the discussion was vague small talk with no real ask — \
then return an empty task list.
- Tasks are internal to-dos for company staff (prepare X, schedule Y, send Z, \
procure W, design V...). 3–12 tasks is typical; cover preparation, client-facing \
deliverables and follow-through, not just the obvious first step.
- phase: sales (winning the deal), proposal (pricing/offer docs), preparation \
(getting ready to deliver), delivery (doing the work), payment, closure.
- required_skill: one of the team's existing skills, or 'general' if none \
applies. Do not invent new skill names.
- due_in_days: working estimate from today; respect any dates the client gave.
- depends_on: titles of OTHER tasks in this list that must finish first.
- visible_to_client: true only when the client should hear about its completion.
- commitment: attach when the task fulfils a promise someone actually stated \
in the discussion — a deliverable with a stated deadline, or something the \
client said they will provide (direction "ours" = we promised the client, \
"theirs" = the client promised us). Internal work nobody promised anyone \
carries no commitment.
  commitment.text must be a SELF-CONTAINED sentence describing what THIS task \
delivers — never a quoted clause from the discussion. Do not begin it with \
"and", do not let it trail off, and do not give two tasks the same wording. \
One spoken sentence often contains SEVERAL promises ("we will handle the \
procurement and delivery of the kits" is two: procure, and deliver) — give \
each task the promise IT fulfils, in its own words. This text is shown to the \
CLIENT verbatim in the weekly report, so it must read as a complete promise on \
its own line.
- objective: one factual line describing the engagement, composed from the \
discussed facts (scope, size, duration, dates) — later meetings are checked \
against it for contradictions.
- program_match: the catalogue offering this engagement belongs to, EXACTLY as \
listed, or "" when none fits.
- pricing_quantity: the count the client mentioned that pricing scales with \
(participants, seats, licences, units, sites...), or 0 when none was mentioned. \
This is only used to look up the company's own pricing table.
- complaints: something the client is UNHAPPY about that already happened \n— a service failure, a missed date, a quality problem, someone not turning \nup. Say what went wrong in their words and who raised it. A request, a \nquestion, or a change of plan is NOT a complaint; neither is a risk nobody \nhas experienced yet. Leave the list empty when nothing went wrong.
- new_facts: reusable facts about this client worth remembering (constraints, \
preferences, infrastructure, names) — not the tasks themselves.
- stakeholders: every CLIENT-side person the discussion actually names or \
identifies. role = what the client's own organisation calls them, as a short \
snake_case label in THEIR vocabulary (cto, procurement_head, store_manager, \
plant_supervisor, site_lead...) — never force-fit a label from another \
industry. influence = how much their word weighs, judged from the discussion: \
decision_maker (their word is final), influencer (shapes the decision), \
gatekeeper (controls access to something, e.g. payments or premises). \
receives_updates = true for the day-to-day contact who should hear progress. \
Never invent people who were not in the discussion."""

_INITIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concrete": {"type": "boolean"},
        "summary": {"type": "string"},
        "objective": {"type": "string"},
        "project_name": {"type": "string"},
        "program_match": {"type": "string"},
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
        "pricing_quantity": {"type": "integer"},
        "tasks": {"type": "array", "items": _TASK_ITEM_SCHEMA},
        "new_facts": {"type": "array", "items": {"type": "string"}},
        "stakeholders": {
            "type": "array", "maxItems": 10, "items": _STAKEHOLDER_ITEM_SCHEMA,
        },
        "complaints": {
            "type": "array", "maxItems": 5, "items": _COMPLAINT_ITEM_SCHEMA,
        },
        "confidence": {"type": "number"},
    },
    "required": ["concrete", "summary", "tasks"],
}


def agreed_block(agreed_tasks: list[dict[str, Any]] | None, *, merging: bool) -> str:
    """The to-dos a human already confirmed at the meeting review gate.

    They are the human's decision, not a suggestion, so the model is told to
    carry them into the plan rather than re-derive (and duplicate) them. Empty
    when nothing was confirmed — the model then plans from the record alone."""
    if not agreed_tasks:
        return ""
    # Each field on its own labelled line so the model never folds the due
    # date or the context back into the task's title (which it does if they
    # share a line — the title then reads "Send the proposal (due …) — …").
    blocks = []
    for i, t in enumerate(agreed_tasks, 1):
        rows = [f"{i}. title: {t.get('title', '')}"]
        due = t.get("due_date")
        if hasattr(due, "strftime"):
            rows.append(f"   due_date: {due:%Y-%m-%d}")
        desc = (t.get("description") or "").strip()
        if desc:
            rows.append(f"   context: {desc}")
        blocks.append("\n".join(rows))
    tail = (
        "Carry each of them into the plan: as a new task whose `title` is the "
        "title above verbatim (nothing appended — the due date goes in the "
        "`due_in_days`/`due_date` field, the context in `description`), or — "
        "when the snapshot already holds an equivalent task — by leaving that "
        "task alone. Never emit a second, near-duplicate task for one listed here."
        if merging else
        "Every one of them must appear in your task list as a task whose "
        "`title` is the title above verbatim — do NOT append the due date or "
        "context to the title; the due date goes in the `due_in_days`/"
        "`due_date` field and the context in `description`. Keep any due date "
        "given here. Never emit a second, near-duplicate task for the same "
        "work. Then add whatever further tasks the discussion implies that "
        "this list misses."
    )
    return (
        "\n\n=== TO-DOS A HUMAN ALREADY CONFIRMED FROM THIS DISCUSSION ===\n"
        + "\n".join(blocks)
        + f"\n{tail}"
    )


async def generate_initial_plan(
    db: AsyncSession,
    *,
    org_id: str,
    lead_name: str,
    text: str,
    agreed_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """First meeting → validated plan spec. Raises PlanningUnavailable when
    the model cannot answer (caller holds the meeting for a human)."""
    ctx = await _org_context(db, org_id)
    # The date the model resolves "next Friday" against must be the
    # organisation's, not UTC's — `agents/base.py` already says the
    # organisation's, and two prompts naming different days is how a plan
    # and a chat answer end up a day apart.
    today = clock.today(await clock.org_zone(db, org_id)).strftime("%A, %d %B %Y")
    result = await _ask(
        purpose="planner.generate_initial_plan",
        org_id=org_id,
        system=_INITIAL_SYSTEM,
        user_content=(
            f"Today is {today}.\nClient: {lead_name}\n\n{_context_block(ctx)}\n\n"
            f"Discussion record:\n{text[:100_000]}"
            + agreed_block(agreed_tasks, merging=False)
        ),
        schema=_INITIAL_SCHEMA,
        required_keys=("concrete", "summary", "tasks"),
    )
    tasks, gaps = validate_task_specs(result.get("tasks"), ctx["skills"])
    program_names = {p["name"] for p in ctx["programs"]}
    program_match = result.get("program_match") or ""
    return {
        "concrete": bool(result.get("concrete")) and bool(tasks),
        "summary": str(result.get("summary") or "")[:1000],
        "objective": str(result.get("objective") or result.get("summary") or "")[:1000],
        "project_name": str(result.get("project_name") or "")[:200],
        "program_match": program_match if program_match in program_names else None,
        "start_date": _parse_iso_date(result.get("start_date")),
        "end_date": _parse_iso_date(result.get("end_date")),
        "pricing_quantity": max(0, int(result.get("pricing_quantity") or 0)),
        "tasks": tasks,
        "skill_gaps": gaps,
        "new_facts": [
            str(f).strip()[:200] for f in (result.get("new_facts") or [])
            if isinstance(f, str) and f.strip()
        ][:10],
        "stakeholders": validate_stakeholder_specs(result.get("stakeholders")),
        "complaints": validate_complaints(result.get("complaints")),
        "confidence": float(result.get("confidence") or 0.75),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Plan merge — new information vs the active plan → diff in op vocabulary
# ─────────────────────────────────────────────────────────────────────────────

_MERGE_SYSTEM = """You are the planning engine of a services company's \
operations platform. A project already has an active plan. New information \
arrived (a meeting, a client message, or a progress note). Produce the DIFF — \
never a whole new plan.

You may:
- add tasks (new_tasks — same rules as any task: internal work only, real \
skills, dependencies by title within new_tasks);
- move dates: {"op":"redate","task_id":...,"new_due":"YYYY-MM-DD"} — this is \
THE op for changing when existing OPEN work happens; when delivery shifts, \
redate every affected open task;
- cancel tasks that the new information makes unnecessary \
({"op":"cancel","task_id":...,"reason":...});
- reopen a DONE task the new information invalidates \
({"op":"reopen","task_id":...,"reason":...,"new_due":...});
- unblock ({"op":"unblock","task_id":...});
- move the project window: {"op":"set_window","start":"YYYY-MM-DD",\
"end":"YYYY-MM-DD"} — include ONLY the side(s) that changed; an omitted side \
stays as it is;
- move a DEMO the client asked to shift: {"op":"reschedule_demo",\
"demo_id":...,"new_date":"YYYY-MM-DD","new_time":"HH:MM"} — use this, \
and ONLY this, when the client asks to move a demo, site visit or \
walkthrough. Do NOT "redate" a task whose title merely mentions the demo: \
that moves our internal to-do and leaves the client holding the old \
calendar invite. demo_id must come from the snapshot demo list. \
- renegotiate a promise made to/by the client: {"op":"renegotiate_commitment",\
"commitment_id":...,"new_due":"YYYY-MM-DD"} — ONLY for commitments whose \
promised date was explicitly renegotiated; ordinary task rescheduling is \
"redate", not this.

PROMISES — record NEW ones, do not only re-date old ones. When a new_tasks item \
fulfils a promise someone actually stated in THIS new information, attach its \
"commitment": a deliverable with a stated deadline, or something the client \
said they will provide (direction "ours" = we promised the client, "theirs" = \
the client promised us). Internal work nobody promised anyone carries no \
commitment. A promise made in a later discussion is exactly as binding as one \
made in the first, and it is only chased if it is recorded here.

Do NOT attach a commitment for a promise that already appears under "Open \
commitments" in the snapshot — it is already being tracked, and a second row \
would double-count it. Reading promises back, summarising them, or confirming \
them is not making new ones. If such a promise moved, use \
renegotiate_commitment with its id; if it is unchanged, emit nothing for it.

CONFLICTS — the most important rule: when the new information CONTRADICTS \
something already committed (a different duration, scope, price expectation, \
date, or deliverable than what the objective, an open task, or a commitment \
records) and TWO DIFFERENT PEOPLE are each maintaining their version, do NOT \
pick a side. Raise it in conflicts[] with a description naming both sides \
("X says ...; Y says ..."), and do NOT emit ops that apply either side.

NOT conflicts: an update is not a disagreement. When the client's decision \
maker (or the same person who set the old value) announces a change — a \
postponement, a moved date, a renovation delay, an extension — that \
SUPERSEDES the old value: apply it with redate/set_window ops. Additions \
that merely extend the plan are also not conflicts. A conflict exists only \
while two sides are simultaneously insisting on different things.

Only reference task_id / commitment_id values that appear in the snapshot. \
Never invent prices. changes[] is the human-readable diff, one line per change. \
no_change=true when the new information needs no plan change at all.

complaints[]: anything the client is UNHAPPY about that already happened — a \nservice failure, a missed date, a quality problem, someone not turning up. \nSay what went wrong and who raised it. A request or a change of plan is not \na complaint. Empty when nothing went wrong.

stakeholders[]: CLIENT-side people the new information names who are missing \
from the snapshot's known-people list, or whose standing it clearly changes \
(a new day-to-day contact, someone newly controlling payments). role = a short \
snake_case label in the client's OWN vocabulary; influence = decision_maker / \
influencer / gatekeeper; receives_updates = true for a day-to-day contact. \
Do not repeat known people whose standing is unchanged; never invent people. \
Discovering a person is not by itself a plan change — no_change stays true \
when the plan itself needs nothing. \
Set other_engagement=true when the person's involvement is a DIFFERENT piece \
of business from this project — another site, campus, branch, or a separate \
future programme mentioned in passing. They are still recorded as a person at \
this client; they are simply not a stakeholder ON THIS PROJECT.

Keep the diff COMPACT: emit each op at most once per task, no repetition, \
typically well under 20 ops and 15 new tasks. A diff is the smallest set of \
changes that makes the plan match reality."""

_MERGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "no_change": {"type": "boolean"},
        "summary": {"type": "string"},
        "changes": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        "new_tasks": {"type": "array", "maxItems": 20, "items": _TASK_ITEM_SCHEMA},
        "ops": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": sorted(VALID_OPS)},
                    "task_id": {"type": "string"},
                    "commitment_id": {"type": "string"},
                    "demo_id": {"type": "string"},
                    "new_date": {"type": "string"},
                    "new_time": {"type": "string"},
                    "new_due": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["op"],
            },
        },
        "conflicts": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
                "required": ["description"],
            },
        },
        "new_facts": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "stakeholders": {
            "type": "array", "maxItems": 10, "items": _STAKEHOLDER_ITEM_SCHEMA,
        },
        "complaints": {
            "type": "array", "maxItems": 5, "items": _COMPLAINT_ITEM_SCHEMA,
        },
        "confidence": {"type": "number"},
    },
    "required": ["no_change", "summary", "changes", "new_tasks", "ops", "conflicts"],
}


async def generate_plan_merge(
    db: AsyncSession,
    *,
    org_id: str,
    project: Any,
    text: str,
    source_kind: str = "meeting",
    agreed_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """New information on an existing project → validated diff."""
    from app.core.constants import ActionItemStatus, CommitmentStatus
    from app.models.action_item import ActionItem
    from app.models.lead import Contact, Lead, ClientIntelligence
    from app.models.project import ClientCommitment, Stakeholder

    tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.status.notin_(
                    [ActionItemStatus.CANCELLED.value, ActionItemStatus.SUPERSEDED.value]
                ),
            )
        )
    ).scalars().all()
    from app.core.constants import DemoStatus
    from app.models.demo import Demo

    # A demo the model cannot SEE is a demo it cannot move. "Please shift the
    # demo to the 15th" used to re-date the nearest demo-ish TASK instead, while
    # the demo itself kept its original date.
    demos = (
        await db.execute(
            select(Demo).where(
                Demo.org_id == org_id,
                Demo.lead_id == project.lead_id,
                Demo.status == DemoStatus.SCHEDULED.value,
            )
        )
    ).scalars().all()
    commitments = (
        await db.execute(
            select(ClientCommitment).where(
                ClientCommitment.project_id == project.id,
                ClientCommitment.status == CommitmentStatus.OPEN.value,
            )
        )
    ).scalars().all()
    intelligence = (
        await db.execute(
            select(ClientIntelligence)
            .where(ClientIntelligence.lead_id == project.lead_id)
            .order_by(ClientIntelligence.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    lead = (
        await db.execute(select(Lead).where(Lead.id == project.lead_id))
    ).scalar_one_or_none()

    snapshot_lines = [
        f"Project: {project.name}",
        f"Objective (committed understanding): {project.objective or '—'}",
        f"Status: {project.status}",
        f"Window: {project.start_date:%Y-%m-%d} → " if project.start_date else "Window: not set",
    ]
    if project.start_date:
        snapshot_lines[-1] = (
            f"Window: {project.start_date:%Y-%m-%d} → "
            + (f"{project.target_end_date:%Y-%m-%d}" if project.target_end_date else "open")
        )
    snapshot_lines.append("\nTasks (id | title | status | due | phase):")
    for t in tasks:
        snapshot_lines.append(
            f"- {t.id} | {t.title} | {t.status} | "
            + (f"{t.due_date:%Y-%m-%d}" if t.due_date else "no due date")
            + f" | {t.phase or '—'}"
        )
    if not tasks:
        snapshot_lines.append("- (none)")
    snapshot_lines.append("\nScheduled demos (id | date | time):")
    for d in demos:
        snapshot_lines.append(
            f"- {d.id} | {d.scheduled_date} | {d.scheduled_time or 'no time'}"
        )
    if not demos:
        snapshot_lines.append("- (none)")
    snapshot_lines.append("\nOpen commitments (id | text | due):")
    for c in commitments:
        snapshot_lines.append(
            f"- {c.id} | {c.text} | " + (f"{c.due_date:%Y-%m-%d}" if c.due_date else "no date")
        )
    if not commitments:
        snapshot_lines.append("- (none)")
    if intelligence:
        snapshot_lines.append("\nKnown facts about this client:")
        snapshot_lines += [f"- {i.note}" for i in intelligence]
    people = (
        await db.execute(
            select(Stakeholder, Contact)
            .join(Contact, Contact.id == Stakeholder.contact_id)
            .where(Stakeholder.project_id == project.id)
        )
    ).all()
    snapshot_lines.append("\nKnown client-side people (name | role | influence):")
    for st, c in people:
        snapshot_lines.append(
            f"- {c.name} | {st.role_at_client or '—'} | {st.influence or '—'}"
        )
    if not people:
        snapshot_lines.append("- (none recorded yet)")

    ctx = await _org_context(db, org_id)
    # The date the model resolves "next Friday" against must be the
    # organisation's, not UTC's — `agents/base.py` already says the
    # organisation's, and two prompts naming different days is how a plan
    # and a chat answer end up a day apart.
    today = clock.today(await clock.org_zone(db, org_id)).strftime("%A, %d %B %Y")
    result = await _ask(
        purpose="planner.generate_plan_merge",
        org_id=org_id,
        system=_MERGE_SYSTEM,
        user_content=(
            f"Today is {today}.\nClient: {lead.name if lead else '—'}\n\n"
            f"{_context_block(ctx)}\n\n=== CURRENT PLAN SNAPSHOT ===\n"
            + "\n".join(snapshot_lines)
            + f"\n\n=== NEW INFORMATION ({source_kind}) ===\n{text[:100_000]}"
            + agreed_block(agreed_tasks, merging=True)
        ),
        schema=_MERGE_SCHEMA,
        required_keys=("no_change", "summary", "changes", "new_tasks", "ops", "conflicts"),
    )
    new_tasks, gaps = validate_task_specs(result.get("new_tasks"), ctx["skills"])
    ops = validate_ops(
        result.get("ops"),
        known_task_ids={t.id for t in tasks},
        known_commitment_ids={c.id for c in commitments},
        known_demo_ids={d.id for d in demos},
    )
    # Fill old_due for redates from the snapshot so the approval card can show
    # the movement honestly.
    due_by_id = {t.id: t.due_date for t in tasks}
    for op in ops:
        if op["op"] == "redate":
            old = due_by_id.get(op["task_id"])
            op["old_due"] = old.isoformat() if old else op["new_due"]
    conflicts = [
        str(c.get("description") or "").strip()[:1000]
        for c in (result.get("conflicts") or [])
        if isinstance(c, dict) and str(c.get("description") or "").strip()
    ][:5]
    return {
        "no_change": bool(result.get("no_change"))
        and not new_tasks and not ops and not conflicts,
        "summary": str(result.get("summary") or "")[:1000],
        "changes": [
            str(c).strip()[:300] for c in (result.get("changes") or [])
            if isinstance(c, str) and c.strip()
        ][:20],
        "new_tasks": new_tasks,
        "ops": ops,
        "conflicts": conflicts,
        "skill_gaps": gaps,
        "new_facts": [
            str(f).strip()[:200] for f in (result.get("new_facts") or [])
            if isinstance(f, str) and f.strip()
        ][:10],
        "stakeholders": validate_stakeholder_specs(result.get("stakeholders")),
        "complaints": validate_complaints(result.get("complaints")),
        "confidence": float(result.get("confidence") or 0.75),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Transcript↔project verification (the "wrong project" guard, generic)
# ─────────────────────────────────────────────────────────────────────────────


async def verify_transcript_project(
    *,
    org_id: str,
    text: str,
    project_name: str,
    lead_name: str,
    other_lead_names: list[str],
) -> dict[str, Any]:
    """Does this transcript plausibly belong to this project/client?
    Returns {"matches": bool, "likely_client": str|None, "reason": str}."""
    schema = {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean"},
            "likely_client": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["matches", "reason"],
    }
    result = await _ask(
        purpose="planner.verify_transcript_project",
        org_id=org_id,
        system=(
            "You check whether a discussion record was filed under the right "
            "client. matches=false ONLY when the record clearly concerns a "
            "DIFFERENT client (e.g. it names another organisation from the "
            "list as the counterparty). Ambiguity or no client name at all "
            "means matches=true — most notes never name the client."
        ),
        user_content=(
            f"Filed under client: {lead_name} (project: {project_name})\n"
            f"Other clients of this organisation: {', '.join(other_lead_names[:100]) or '—'}\n\n"
            f"Discussion record:\n{text[:50_000]}"
        ),
        schema=schema,
        required_keys=("matches", "reason"),
        tier="fast",
        max_tokens=4096,
    )
    likely = str(result.get("likely_client") or "").strip()
    return {
        "matches": bool(result.get("matches", True)),
        "likely_client": likely or None,
        "reason": str(result.get("reason") or "")[:500],
    }


# ─────────────────────────────────────────────────────────────────────────────
# People a meeting names, checked before they become contacts (1 Oct 2026)
# ─────────────────────────────────────────────────────────────────────────────

_PEOPLE_SYSTEM = (
    "You tidy up the list of people a business meeting mentioned on the "
    "client's side, before they are saved as contacts. The names come from "
    "speech-to-text, which often misspells them.\n\n"
    "For each entry in NEW PEOPLE return:\n"
    "- is_person: true when it names an individual (a name, a first name, or "
    "an honorific with a surname such as 'Mr. Jain'); false when it is only a "
    "role, job title, team or department with no name ('Accounts Head', 'the "
    "finance team').\n"
    "- same_as: the index of an EARLIER entry in NEW PEOPLE that is the same "
    "individual, else null; same_as_score from 0 to 1.\n"
    "- contact: the index of the SAVED CONTACT most likely to be the same "
    "individual, else null; contact_score from 0 to 1.\n"
    "- reason: a few words.\n\n"
    "Scores: 1 means certainly the same individual, 0 certainly different. "
    "Spelling or transcription variants of one name (for example Rishabh and "
    "Risabh), a first name alone, or an honorific with the surname, when the "
    "rest fits only one person, score high. A different first name scores low "
    "even with the same surname. A role-only entry matches a saved contact "
    "only when that contact's title is that role. Merging two different "
    "people is worse than keeping a duplicate, so do not score high on a "
    "guess."
)

_PEOPLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "is_person": {"type": "boolean"},
                    "same_as": {"type": "integer", "nullable": True},
                    "same_as_score": {"type": "number"},
                    "contact": {"type": "integer", "nullable": True},
                    "contact_score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "is_person", "contact_score"],
            },
        },
    },
    "required": ["people"],
}


def _score(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def parse_people_review(
    raw: Any, *, people_count: int, contact_count: int
) -> dict[int, dict[str, Any]]:
    """The model's answer → {person index: {is_person, same_as, same_as_score,
    contact, contact_score}} for EVERY person. A person it said nothing about
    is a person matching nothing; an index that points nowhere (or, for
    same_as, not at an earlier entry) is dropped; scores are clamped to 0..1."""
    out: dict[int, dict[str, Any]] = {
        i: {"is_person": True, "same_as": None, "same_as_score": 0.0,
            "contact": None, "contact_score": 0.0}
        for i in range(people_count)
    }
    items = raw.get("people") if isinstance(raw, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        i = item.get("index")
        if not isinstance(i, int) or i not in out:
            continue
        same_as = item.get("same_as")
        if not (isinstance(same_as, int) and 0 <= same_as < i):
            same_as = None
        contact = item.get("contact")
        if not (isinstance(contact, int) and 0 <= contact < contact_count):
            contact = None
        out[i] = {
            "is_person": item.get("is_person") is not False,
            "same_as": same_as,
            "same_as_score": _score(item.get("same_as_score")) if same_as is not None else 0.0,
            "contact": contact,
            "contact_score": _score(item.get("contact_score")) if contact is not None else 0.0,
        }
    return out


async def review_meeting_people(
    *,
    org_id: str,
    people: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Ask the model about the people a meeting named: person or only a role,
    the same as an earlier name in this meeting, the same as a saved contact
    (scores 0..1). Uses the strong tier, as proposal writing does. Raises
    PlanningUnavailable when no usable answer comes back."""
    saved = "\n".join(
        f"{i}. {c['name']}" + (f" (title: {c['title']})" if c.get("title") else "")
        for i, c in enumerate(contacts)
    ) or "(none)"
    new = "\n".join(
        f"{i}. {p['name']}" + (f" (role in the meeting: {p['role']})" if p.get("role") else "")
        for i, p in enumerate(people)
    )
    result = await _ask(
        purpose="planner.review_meeting_people",
        org_id=org_id,
        system=_PEOPLE_SYSTEM,
        user_content=f"SAVED CONTACTS:\n{saved}\n\nNEW PEOPLE:\n{new}",
        schema=_PEOPLE_SCHEMA,
        required_keys=("people",),
        tier="strong",
        max_tokens=4096,
    )
    return parse_people_review(result, people_count=len(people),
                               contact_count=len(contacts))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rejection-note instruction parsing (generic "give X to Sourav")
# ─────────────────────────────────────────────────────────────────────────────


async def parse_rejection_note(
    *,
    org_id: str,
    note: str,
    tasks: list[Any],
    users: list[Any],
) -> list[dict[str, str]]:
    """A plan rejection note may carry reassignment instructions in any
    phrasing. Returns [{"task_id", "user_id"}] — only ids that exist."""
    if not note.strip() or not tasks or not users:
        return []
    schema = {
        "type": "object",
        "properties": {
            "reassignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "user_id": {"type": "string"},
                    },
                    "required": ["task_id", "user_id"],
                },
            },
        },
        "required": ["reassignments"],
    }
    result = await _ask(
        purpose="planner.parse_rejection_note",
        org_id=org_id,
        system=(
            "A manager rejected an AI-drafted plan with a note. Extract any "
            "REASSIGNMENT instructions (a named person should do a specific "
            "task) as task_id/user_id pairs from the lists given. Ignore "
            "everything that is not a clear reassignment. Empty list when none."
        ),
        user_content=(
            "Tasks (id | title):\n"
            + "\n".join(f"- {t.id} | {t.title}" for t in tasks[:50])
            + "\n\nTeam (id | name):\n"
            + "\n".join(f"- {u.id} | {u.name}" for u in users[:100])
            + f"\n\nRejection note:\n{note[:2000]}"
        ),
        schema=schema,
        required_keys=("reassignments",),
        tier="fast",
        max_tokens=4096,
    )
    task_ids = {t.id for t in tasks}
    user_ids = {u.id for u in users}
    out = []
    for r in result.get("reassignments") or []:
        if isinstance(r, dict) and r.get("task_id") in task_ids and r.get("user_id") in user_ids:
            out.append({"task_id": r["task_id"], "user_id": r["user_id"]})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 5. Phase wave without a playbook — generate the wave from the project itself
# ─────────────────────────────────────────────────────────────────────────────


async def generate_phase_wave(
    db: AsyncSession, *, org_id: str, project: Any, phase: str, anchor: datetime
) -> tuple[list[dict[str, Any]], list[str]]:
    """No playbook exists for this program+phase → derive the phase's task
    wave from the project's own objective and history. Returns (task specs
    with absolute due dates, skill gaps)."""
    from app.core.constants import ActionItemStatus
    from app.models.action_item import ActionItem

    done_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.status.notin_(
                    [ActionItemStatus.CANCELLED.value, ActionItemStatus.SUPERSEDED.value]
                ),
            )
        )
    ).scalars().all()
    ctx = await _org_context(db, org_id)
    schema = {
        "type": "object",
        "properties": {"tasks": {"type": "array", "items": _TASK_ITEM_SCHEMA}},
        "required": ["tasks"],
    }
    result = await _ask(
        purpose="planner.generate_phase_wave",
        org_id=org_id,
        system=(
            "A project just entered a new phase and no standard playbook "
            "exists for it. Generate the wave of internal tasks this phase "
            "needs, derived from the project's objective and what was already "
            "done. due_in_days counts from the anchor date given (use small "
            "numbers for work needed before/at the anchor). Do not repeat "
            "tasks that already exist."
        ),
        user_content=(
            f"Project: {project.name}\nObjective: {project.objective or '—'}\n"
            f"New phase: {phase}\nAnchor date: {anchor:%Y-%m-%d}\n\n"
            f"{_context_block(ctx)}\n\nExisting tasks:\n"
            + "\n".join(f"- {t.title} ({t.status})" for t in done_tasks[:60])
        ),
        schema=schema,
        required_keys=("tasks",),
    )
    specs, gaps = validate_task_specs(result.get("tasks"), ctx["skills"])
    for s in specs:
        s["due_date"] = anchor + timedelta(days=s.pop("due_in_days", 7))
        s["phase"] = phase if phase in VALID_PHASES else s["phase"]
    return specs, gaps


async def generate_scope_wave(
    db: AsyncSession, *, org_id: str, project: Any, change_detail: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """A client asked to GROW a running project's scope. Derive the small
    wave of internal tasks the addition needs from the project's own
    objective — any topic, no template. Money stays out of the model's
    hands: amendments price from the locked proposal elsewhere. Returns
    (task specs with due_in_days, skill gaps)."""
    from app.core.constants import ActionItemStatus
    from app.models.action_item import ActionItem

    existing = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.status.notin_(
                    [ActionItemStatus.CANCELLED.value, ActionItemStatus.SUPERSEDED.value]
                ),
            )
        )
    ).scalars().all()
    ctx = await _org_context(db, org_id)
    schema = {
        "type": "object",
        "properties": {
            "tasks": {"type": "array", "items": _TASK_ITEM_SCHEMA, "maxItems": 8},
        },
        "required": ["tasks"],
    }
    result = await _ask(
        purpose="planner.generate_scope_wave",
        org_id=org_id,
        system=(
            "A client asked to EXPAND the scope of a running project. "
            "Generate the small wave (2–6) of internal tasks the addition "
            "needs, derived from the project's objective and the request. "
            "Include updating any client-facing deliverables the addition "
            "touches, extra procurement/logistics if physical goods are "
            "involved, and an 'amend the invoice for the confirmed addition' "
            "task — but NEVER invent amounts or prices; the numbers are "
            "computed elsewhere. Do not repeat tasks that already exist."
        ),
        user_content=(
            f"Project: {project.name}\nObjective: {project.objective or '—'}\n"
            f"Scope addition requested:\n{change_detail[:2_000]}\n\n"
            f"{_context_block(ctx)}\n\nExisting tasks:\n"
            + "\n".join(f"- {t.title} ({t.status})" for t in existing[:60])
        ),
        schema=schema,
        required_keys=("tasks",),
    )
    return validate_task_specs(result.get("tasks"), ctx["skills"])


async def pick_skill(
    *,
    org_id: str,
    work: str,
    skills: list[str],
) -> str | None:
    """Name the org-taxonomy skill that best fits a piece of work, or None
    when nothing fits (the assignment engine then routes without a skill and
    a human confirms)."""
    if not skills:
        return None
    schema = {
        "type": "object",
        "properties": {"skill": {"type": "string"}},
        "required": ["skill"],
    }
    result = await _ask(
        purpose="planner.pick_skill",
        org_id=org_id,
        system=(
            "Given work to be done and an organisation's skill taxonomy, "
            "reply with the single most fitting skill copied EXACTLY from "
            "the list, or an empty string when none genuinely fits — never "
            "invent a skill name."
        ),
        user_content=(
            f"Work:\n{work[:2_000]}\n\nSkill taxonomy:\n- " + "\n- ".join(skills[:60])
        ),
        schema=schema,
        required_keys=("skill",),
        tier="fast",
        max_tokens=2048,
    )
    picked = _norm_skill(result.get("skill"))
    return picked if picked in set(skills) else None


# ─────────────────────────────────────────────────────────────────────────────
# 6. Inbound project disambiguation (which project is this message about?)
# ─────────────────────────────────────────────────────────────────────────────


async def select_answer_facts(
    *,
    org_id: str,
    question: str,
    facts: list[str],
) -> dict[str, Any]:
    """A client asked a question; `facts` is everything the company has on
    record that might answer it. The model judges — by meaning, not shared
    words — which facts genuinely help and whether they SUFFICE for an honest
    answer. Returns {"sufficient": bool, "fact_indexes": [int, ...]};
    insufficient simply sends the question to a human, which is the correct
    outcome when the data isn't there."""
    if not facts:
        return {"sufficient": False, "fact_indexes": []}
    schema = {
        "type": "object",
        "properties": {
            "sufficient": {"type": "boolean"},
            "fact_indexes": {
                "type": "array",
                "items": {"type": "integer"},
                "maxItems": 12,
            },
        },
        "required": ["sufficient", "fact_indexes"],
    }
    result = await _ask(
        purpose="inbound.select_answer_facts",
        org_id=org_id,
        system=(
            "A client asked a company a question. You are shown the company's "
            "own recorded knowledge, numbered. Pick the indexes of the items "
            "that genuinely help answer THIS question — judge by meaning, not "
            "by shared words. Set sufficient=true ONLY when the picked items "
            "honestly answer the question; never stretch loosely related "
            "facts, and never rely on your own general knowledge — an answer "
            "may come only from these items. sufficient=false routes the "
            "question to a human, which is the right outcome when the data "
            "is not there."
        ),
        user_content=(
            f"Question:\n{question[:2_000]}\n\nRecorded knowledge:\n"
            + "\n".join(f"[{i}] {f[:400]}" for i, f in enumerate(facts[:30]))
        ),
        schema=schema,
        required_keys=("sufficient", "fact_indexes"),
        tier="fast",
        max_tokens=4096,
    )
    picked: list[int] = []
    for raw in result.get("fact_indexes") or []:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(facts) and idx not in picked:
            picked.append(idx)
    # Deterministic fence: "sufficient" without a single named fact would let
    # the model answer from thin air — treat it as insufficient.
    sufficient = bool(result.get("sufficient")) and bool(picked)
    return {"sufficient": sufficient, "fact_indexes": picked}


async def match_message_project(
    *,
    org_id: str,
    text: str,
    projects: list[Any],
    source_kind: str = "message",
) -> list[str]:
    """Given a client message (or meeting) and the client's projects, return
    the ids of the project(s) it concerns: one id normally, several when it
    explicitly spans several projects, empty when it genuinely can't be told
    OR when it is new work none of the listed projects covers."""
    if not projects:
        return []
    schema = {
        "type": "object",
        "properties": {
            "project_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 20,
            }
        },
        "required": ["project_ids"],
    }
    result = await _ask(
        purpose="inbound.match_project",
        org_id=org_id,
        system=(
            f"A client {source_kind} came in; the client already has projects "
            "with this company. Decide which project(s) it concerns. "
            f"Reply with exactly the concerned projects' ids: ONE id when the "
            f"{source_kind} is about one project, SEVERAL ids only when it "
            "explicitly spans them (e.g. 'let us discuss both X and Y'), and "
            "an EMPTY list when it does not clearly concern any specific "
            "listed project — including when it describes NEW work that none "
            "of the listed projects covers. A fresh engagement with an "
            "existing client is new work, not an update to an old project."
        ),
        user_content=(
            "Projects (id | name | objective | status):\n"
            + "\n".join(
                f"- {p.id} | {p.name} | {(p.objective or '')[:150]} | {p.status}"
                for p in projects[:20]
            )
            + f"\n\n{source_kind.capitalize()}:\n{text[:20_000]}"
        ),
        schema=schema,
        required_keys=("project_ids",),
        tier="fast",
        max_tokens=4096,
    )
    known = {p.id for p in projects}
    picked: list[str] = []
    for raw in result.get("project_ids") or []:
        pid = str(raw or "").strip()
        if pid in known and pid not in picked:
            picked.append(pid)
    return picked
