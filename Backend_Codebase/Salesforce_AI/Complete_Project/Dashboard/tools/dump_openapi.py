"""Dump the backend's OpenAPI spec and its closed vocabularies for the console.

Lives under Dashboard/ on purpose: nothing dashboard-related goes under app/
(05_DECISIONS.md D19). It imports the FastAPI app rather than fetching from a
running server, so generation works with the backend down (06_DESIGN.md §3.1) —
verified by comparing this output key-for-key against the spec served on :8000.

Two files are written, both consumed by tools/gen.mjs:

  src/api/openapi.json               the spec, verbatim
  src/api/vocabularies.generated.ts  the enums the API validates in handler
                                     bodies, which OpenAPI therefore cannot
                                     carry (07_BUILD_PLAN.md P3/A4)
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent   # Complete_Project/
sys.path.insert(0, str(ROOT))

import app.models                                     # noqa: E402,F401
from app.core import constants                        # noqa: E402
from app.core import reset_taxonomy                    # noqa: E402
from app.database import Base                         # noqa: E402
from app.main import app                              # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "src" / "api"


def _members(enum) -> list[str]:
    return [m.value for m in enum]


# ─────────────────────────────────────────────────────────────────────────────
# Which tables a reset touches, and which flag reaches each bucket
# ─────────────────────────────────────────────────────────────────────────────
#
# `POST /admin/reset` returns a **flat** `counts` dict keyed by table name, and
# only for the tables the flags it was called with actually cover. So the
# console cannot group a dry run into buckets, cannot name the fourth bucket at
# all, and cannot label a flag with what it clears — none of that is in any
# response. It is `app/core/reset_taxonomy.py`, which is frozen and guarded by
# `tests/test_reset_taxonomy.py`.
#
# Fifty-five table names retyped into TypeScript is fifty-five things that go
# stale in silence, and the failure mode is the worst kind: a table missing from
# the console's WIPE list simply does not appear in the preview, so the operator
# approves a reset having been shown less than it does. Derived here instead.
#
# The bucket lists come from importing the module. The **flag → bucket** mapping
# comes from AST-reading `deletion_order`, because that is where it is decided
# and a comment claiming it would be a second copy.

_RESET_ORDER_FN = "deletion_order"


def _reset_flag_map() -> dict[str, str]:
    """`{"transactional": "WIPE", ...}`, read from `deletion_order`'s body."""
    src = (ROOT / "app" / "core" / "reset_taxonomy.py").read_text("utf-8")
    tree = ast.parse(src)
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == _RESET_ORDER_FN
        ),
        None,
    )
    if fn is None:
        raise ValueError(f"app/core/reset_taxonomy.py has no {_RESET_ORDER_FN}")

    mapping: dict[str, str] = {}
    for node in fn.body:
        # if <flag>: order.extend(<BUCKET>)
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Name):
            continue
        for stmt in node.body:
            call = getattr(stmt, "value", None)
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "extend"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
            ):
                mapping[node.test.id] = call.args[0].id
    if not mapping:
        raise ValueError(f"{_RESET_ORDER_FN} no longer has the shape this reads")
    return mapping


def _reset_taxonomy() -> dict[str, Any]:
    buckets = {
        name: list(getattr(reset_taxonomy, name))
        for name in ("KEEP", "CONFIG", "REPLACE", "WIPE")
    }
    flags = _reset_flag_map()

    # The partition is total and disjoint — `tests/test_reset_taxonomy.py`
    # asserts it against `Base.metadata`. Re-asserted here so a dump can never
    # emit a taxonomy that does not cover the schema it was taken from.
    named = [t for b in buckets.values() for t in b]
    tables = set(Base.metadata.tables)
    if len(named) != len(set(named)) or set(named) != tables:
        raise ValueError(
            "reset taxonomy is not a partition of Base.metadata: "
            f"{len(named)} named, {len(tables)} tables"
        )

    return {
        "buckets": buckets,
        # KEEP is deliberately absent: no flag reaches it, which is the fact.
        "clearedBy": {bucket: flag for flag, bucket in flags.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# What happens to an approval request that matches no rule
# ─────────────────────────────────────────────────────────────────────────────
#
# The go-live check's approval-rule step (06_DESIGN.md §5.6 check 4) has to say
# what an entity type with no catch-all `{}` rule actually costs. That answer
# is NOT the same for every entity type, and it is not in any API response:
#
#   approval_engine.request_approval  →  find_rule returns None
#     · default_approver_role is a role  ⇒ one person still gets asked
#     · default_approver_role is None    ⇒ the caller applies it as "system"
#
# and each of the nine call sites decides for itself. `proposals.py` passes
# None, so a proposal matching no rule is set APPROVED_INTERNALLY with nobody
# looking at it; `planner_engine`'s plan-version path does the same. A console
# that told an operator "no catch-all means no approver" would be wrong in both
# directions at once — too mild for those two, too alarming for the other seven.
#
# So it is derived here rather than hand-typed, for the same reason VOCAB is:
# a table of nine call sites in TypeScript is a table that goes stale silently.
# `gen:check` re-derives it on every build, so moving a call site or adding one
# fails the build instead of quietly making a screen lie.

_APPROVAL_FN = "request_approval"


def _literal_role(node: ast.expr | None) -> str | None:
    """`Role.SALES_LEAD.value` → "sales_lead"; `None` → None.

    Resolved against the real enum rather than by string-munging the attribute
    name, so a renamed member fails loudly here instead of emitting a role that
    does not exist.
    """
    if node is None or (isinstance(node, ast.Constant) and node.value is None):
        return None
    # Role.SALES_LEAD.value
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
    ):
        enum = getattr(constants, node.value.value.id, None)
        member = getattr(enum, node.value.attr, None) if enum is not None else None
        if member is not None:
            return str(member.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise ValueError(f"cannot resolve approval role from {ast.dump(node)}")


def _approval_no_rule() -> dict[str, dict[str, Any]]:
    entity_types = _members(constants.ApprovalEntityType)
    out: dict[str, dict[str, Any]] = {
        e: {"callSites": 0, "fallsTo": []} for e in entity_types
    }

    # The signature's own default, so a call site that omits the keyword is
    # counted as what it actually does rather than skipped.
    engine = ast.parse((ROOT / "app" / "engines" / "approval_engine.py").read_text("utf-8"))
    signature_default: str | None = None
    found_signature = False
    for node in ast.walk(engine):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == _APPROVAL_FN:
            found_signature = True
            args = node.args
            for name, default in zip(args.kwonlyargs, args.kw_defaults):
                if name.arg == "default_approver_role":
                    signature_default = _literal_role(default)
    if not found_signature:
        raise ValueError(f"app/engines/approval_engine.py has no {_APPROVAL_FN}")

    for path in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None
            )
            if name != _APPROVAL_FN:
                continue
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            if "entity_type" not in kwargs:
                continue                      # the definition itself, not a call
            entity = _literal_role(kwargs["entity_type"])
            if entity not in out:
                raise ValueError(f"{path}: unknown approval entity_type {entity!r}")
            falls_to = (
                _literal_role(kwargs["default_approver_role"])
                if "default_approver_role" in kwargs
                else signature_default
            )
            out[entity]["callSites"] += 1
            if falls_to not in out[entity]["fallsTo"]:
                out[entity]["fallsTo"].append(falls_to)

    for entity in out:
        out[entity]["fallsTo"].sort(key=lambda r: (r is not None, r or ""))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ensure_ascii=False plus an explicit utf-8 handle: the route descriptions
    # carry § — →, and both Python and Node default to the system codepage on
    # Windows. A mis-encoded dump makes gen:check diff forever against a file
    # that only looks identical.
    spec = app.openapi()
    (OUT / "openapi.json").write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # A4 — the vocabularies the handlers validate against. `role` and
    # `department` are checked in admin.py's function bodies, not on the
    # Pydantic field, so OpenAPI types them plain `string` and the generated
    # schema cannot constrain them. Generating them here keeps the console from
    # hand-typing a role list: RoleGate.java is one permission behind _MATRIX
    # for exactly that reason (04_OPEN_QUESTIONS.md Q15).
    vocab = {
        "role": _members(constants.Role),
        "org_role": sorted(r.value for r in constants.ORG_ROLES),
        "department": _members(constants.Department),
        "template_kind": _members(constants.TemplateKind),
        "message_channel": _members(constants.MessageChannel),
        "skill_level": _members(constants.SkillLevel),
        "phase": _members(constants.Phase),
    }
    body = json.dumps(vocab, indent=2, ensure_ascii=False)

    # Checklist item 10 is `◐` when every dial still equals its model default,
    # captioned "defaults apply — the API cannot tell whether you chose them"
    # (06_DESIGN.md §5.2). Comparing needs the defaults, and `GET /admin/settings`
    # does not say which values are defaults. Dumping them from the column
    # definitions keeps 25 numbers out of hand-written TypeScript.
    settings_defaults: dict[str, Any] = {}
    for column in Base.metadata.tables["org_settings"].columns:
        # The three *_integration JSON blobs are credentials, not dials, and
        # GET /admin/settings never returns them under these names — only as
        # the *_credentials_stored booleans. Including them would give item 10
        # a default with no field to compare against.
        if column.name in ("id", "org_id", "created_at", "updated_at") or (
            column.name.endswith("_integration")
        ):
            continue
        if column.default is None:
            continue
        value = column.default.arg
        if callable(value):
            value = value(None)          # JSON columns use a lambda default
        try:
            json.dumps(value)
        except TypeError:
            continue                     # not representable; skip rather than guess
        settings_defaults[column.name] = value
    defaults_body = json.dumps(settings_defaults, indent=2, ensure_ascii=False)

    no_rule = _approval_no_rule()
    no_rule_body = json.dumps(no_rule, indent=2, ensure_ascii=False)

    taxonomy = _reset_taxonomy()
    taxonomy_body = json.dumps(taxonomy, indent=2, ensure_ascii=False)

    (OUT / "vocabularies.generated.ts").write_text(
        "// GENERATED by Dashboard/tools/dump_openapi.py — do not edit.\n"
        "// Source: app/core/constants.py. These are enforced in handler bodies,\n"
        "// so they cannot appear in openapi.json (07_BUILD_PLAN.md P3/A4).\n"
        f"export const VOCAB = {body} as const;\n"
        "\n"
        "// Source: app/models/organisation.py · OrgSettings column defaults.\n"
        "// Checklist item 10 compares the live settings against these to decide\n"
        "// whether anything was actually chosen (06_DESIGN.md §5.2).\n"
        f"export const SETTINGS_DEFAULTS = {defaults_body} as const;\n"
        "\n"
        "// Source: every call to approval_engine.request_approval under app/.\n"
        "// What an approval request that matches NO rule falls back to, per\n"
        "// entity type: a role means somebody is still asked, `null` means the\n"
        "// caller applies it unreviewed. The go-live check's approval step\n"
        "// (06_DESIGN.md §5.6 check 4) states the consequence of a missing\n"
        "// catch-all, and the consequence differs per entity type.\n"
        f"export const APPROVAL_NO_RULE = {no_rule_body} as const;\n"
        "\n"
        "// Source: app/core/reset_taxonomy.py (D16). Which tables each reset\n"
        "// flag clears, and the fourth bucket no flag reaches. POST /admin/reset\n"
        "// returns a flat counts dict covering only the flags it was called\n"
        "// with, so the console cannot group a dry run without this.\n"
        f"export const RESET_TAXONOMY = {taxonomy_body} as const;\n",
        encoding="utf-8",
    )

    unreviewed = sorted(k for k, v in no_rule.items() if None in v["fallsTo"])
    print(f"openapi.json              {len(spec['paths'])} paths, "
          f"{len(spec['components']['schemas'])} schemas")
    partition = " · ".join(
        f"{name} {len(rows)}" for name, rows in taxonomy["buckets"].items()
    )
    print(f"vocabularies.generated.ts {len(vocab)} vocabularies, "
          f"{len(no_rule)} approval entity types "
          f"({len(unreviewed)} applied unreviewed with no rule: "
          f"{', '.join(unreviewed) or 'none'})")
    print(f"reset taxonomy            {partition} = "
          f"{sum(len(r) for r in taxonomy['buckets'].values())}")


if __name__ == "__main__":
    main()
