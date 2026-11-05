"""Proposal building and editing.

Correctness rules from doc §12:
  • Numbers NEVER come from the AI — line items and totals are computed here,
    from the organisation's pricing table (or an explicit human instruction).
  • Proposals lock the exact template + pricing version they were built with.
  • The commercial block sits between markers so narrative edits (by the LLM)
    can never touch the numbers: we always re-insert the computed block.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ProposalStatus
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.base import utcnow
from app.models.lead import Contact, Lead
from app.models.organisation import Organisation, OrgSettings
from app.models.program import PricingTable, Program, ProposalTemplate
from app.models.proposal import Proposal, ProposalRevision
from app.models.user import User
from app.services import audit_service, template_service

logger = logging.getLogger(__name__)

PRICING_START = "<!--PRICING_START-->"
PRICING_END = "<!--PRICING_END-->"

_CURRENCY_SYMBOLS = {"INR": "Rs ", "USD": "$", "EUR": "EUR "}


def _money(amount: float, currency: str) -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    if float(amount) == int(amount):
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:,.2f}"


def compute_totals(line_items: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in line_items:
        qty = float(item.get("quantity", 0) or 0)
        price = float(item.get("unit_price", 0) or 0)
        item["line_total"] = round(qty * price, 2)
        total += item["line_total"]
    return round(total, 2)


def render_pricing_block(line_items: list[dict[str, Any]], currency: str) -> str:
    """Markdown table of the commercials — always machine-generated."""
    lines = [
        PRICING_START,
        "",
        "| Item | Unit | Unit Price | Quantity | Line Total |",
        "|------|------|-----------:|---------:|-----------:|",
    ]
    total = 0.0
    for item in line_items:
        total += float(item.get("line_total", 0) or 0)
        lines.append(
            f"| {item.get('label', item.get('code', 'Item'))} "
            f"| {item.get('unit', '-')} "
            f"| {_money(float(item.get('unit_price', 0) or 0), currency)} "
            f"| {int(float(item.get('quantity', 0) or 0))} "
            f"| {_money(float(item.get('line_total', 0) or 0), currency)} |"
        )
    lines += [
        f"| **Total** | | | | **{_money(round(total, 2), currency)}** |",
        "",
        PRICING_END,
    ]
    return "\n".join(lines)


def replace_pricing_block(content_md: str, new_block: str) -> str:
    start = content_md.find(PRICING_START)
    end = content_md.find(PRICING_END)
    if start == -1 or end == -1:
        return content_md.rstrip() + "\n\n## Commercials\n\n" + new_block + "\n"
    return content_md[:start] + new_block + content_md[end + len(PRICING_END):]


async def _current_template(
    db: AsyncSession, org_id: str, program_id: str, template_id: str | None
) -> ProposalTemplate:
    q = select(ProposalTemplate).where(
        ProposalTemplate.org_id == org_id,
        ProposalTemplate.program_id == program_id,
        # D-B: a proposal is never built from an MOU template, even
        # when both are current for this programme.
        ProposalTemplate.document_type == "proposal",
    )
    if template_id:
        q = q.where(ProposalTemplate.id == template_id)
    else:
        q = q.where(ProposalTemplate.is_current.is_(True))
    tmpl = (await db.execute(q.order_by(ProposalTemplate.version.desc()))).scalars().first()
    if tmpl is None:
        raise NotFoundError(
            "No proposal template for this program. Ask your Org Admin to add one."
        )
    return tmpl


async def _current_pricing(db: AsyncSession, org_id: str, program_id: str) -> PricingTable:
    pricing = (
        await db.execute(
            select(PricingTable)
            .where(
                PricingTable.org_id == org_id,
                PricingTable.program_id == program_id,
                PricingTable.is_current.is_(True),
            )
            .order_by(PricingTable.version.desc())
        )
    ).scalars().first()
    if pricing is None:
        raise NotFoundError(
            "No pricing table for this program. Ask your Org Admin to add one."
        )
    return pricing


async def build_proposal(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    lead_id: str,
    program_id: str,
    template_id: str | None = None,
    context_summary: str | None = None,
    quantities: dict[str, float] | None = None,
    project_id: str | None = None,
) -> Proposal:
    """Create a proposal draft from the org's template + current pricing."""
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id, Lead.org_id == ctx.org_id))
    ).scalar_one_or_none()
    if lead is None:
        raise NotFoundError("Lead not found")
    program = (
        await db.execute(
            select(Program).where(Program.id == program_id, Program.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")

    template = await _current_template(db, ctx.org_id, program_id, template_id)
    pricing = await _current_pricing(db, ctx.org_id, program_id)
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()
    org_settings = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == ctx.org_id))
    ).scalar_one_or_none()
    sender = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one_or_none()
    primary_contact = (
        await db.execute(
            select(Contact)
            .where(Contact.org_id == ctx.org_id, Contact.lead_id == lead_id)
            .order_by(Contact.is_primary.desc(), Contact.created_at)
        )
    ).scalars().first()

    # F66: `{context_summary}` is optional on the WIRE but mandatory in the
    # template, and the two never met. `create_proposal` declares `context_note`
    # optional, the model routinely omits it, and the renderer turns an empty
    # value into `[missing:context_summary]` — so "create the proposal for X"
    # reliably produced a draft with a marker where the opening paragraph goes.
    #
    # F47 made that marker BLOCK the send and F61 stopped a stale PDF going out;
    # neither made the draft come out clean, because nothing ever supplied the
    # value. It was never the model's to remember: the project's `objective` is
    # written from the meeting and is exactly the one-or-two sentence summary
    # the template asks for. Read it instead of asking.
    #
    # Nothing is invented. With no project and no objective the marker still
    # appears and F47 still escalates it — an honest blank beats a fabricated
    # paragraph in a document that goes to a client.
    if not (context_summary or "").strip():
        from app.models.project import Project

        stmt = select(Project).where(Project.org_id == ctx.org_id)
        if project_id:
            stmt = stmt.where(Project.id == project_id)
        else:
            # The assistant path passes no project_id (the proposal is created
            # from the LEAD). Newest live project on this lead, oldest-status
            # noise excluded, deterministic on created_at then id.
            stmt = stmt.where(
                Project.lead_id == lead_id,
                Project.status.notin_(("closed", "lost")),
            ).order_by(Project.created_at.desc(), Project.id.desc())
        project = (await db.execute(stmt)).scalars().first()
        if project is not None and (project.objective or "").strip():
            context_summary = project.objective.strip()

    currency = pricing.currency or (org_settings.currency if org_settings else "INR")
    quantities = quantities or {}
    line_items: list[dict[str, Any]] = []
    for item in pricing.items:
        line_items.append(
            {
                "code": item.get("code"),
                "label": item.get("label", item.get("code", "Item")),
                "unit": item.get("unit", "-"),
                "unit_price": float(item.get("unit_price", 0) or 0),
                "quantity": float(quantities.get(item.get("code", ""), item.get("default_quantity", 1) or 1)),
            }
        )
    total = compute_totals(line_items)

    variables: dict[str, Any] = {
        # {client_name} is the neutral name; {school_name} stays as an alias so
        # templates an org already saved keep rendering (finding F11/F6).
        "client_name": lead.name,
        "school_name": lead.name,
        "contact_name": primary_contact.name if primary_contact else "Sir/Madam",
        "contact_title": (primary_contact.title if primary_contact else None) or "",
        "sender_name": sender.name if sender else ctx.email,
        "sender_email": ctx.email,
        "org_name": org.name,
        "program_name": program.name,
        "program_description": program.description or "",
        "context_summary": context_summary or "",
        "date": utcnow().strftime("%d %B %Y"),
        "total_amount": _money(total, currency),
        "pricing_table": render_pricing_block(line_items, currency),
    }
    filled_json: list[dict[str, Any]] = []
    unfilled_placeholders: list[str] = []
    docx_bytes: bytes | None = None

    if getattr(template, "kind", "markdown") == "docx_simple":
        # A simple-flow template is filled through the assistant, tag by tag,
        # with a human confirming every value before anything is written (D13).
        # Falling through to the markdown path below would render body_md --
        # the projected plain text of the document -- so the client would get
        # a proposal still reading "<ask:6 Units>", with none of the branding
        # and nothing having failed. Refuse loudly instead.
        raise ValidationFailedError(
            f"Template '{template.name}' v{template.version} is filled by the "
            "assistant, not built from here. Ask Jarvis to create the proposal "
            "for this client and it will fill the document with you."
        )

    if getattr(template, "kind", "markdown") == "docx":
        # A docx template is filled, never re-rendered: the uploaded document
        # keeps its cover, images, headers, footers and styled tables, and the
        # model only ever supplies plain text for the placeholders a human
        # approved. See
        # docs/superpowers/specs/2026-09-03-docx-proposal-templates-design.md
        from app.models.program import ProposalTemplateDoc
        from app.services import docx_proposal_service, storage

        doc_row = (
            await db.execute(
                select(ProposalTemplateDoc).where(
                    ProposalTemplateDoc.template_id == template.id,
                    ProposalTemplateDoc.org_id == ctx.org_id,
                )
            )
        ).scalar_one_or_none()
        if doc_row is None:
            raise NotFoundError(
                f"Template '{template.name}' v{template.version} is a document "
                "template but its file is missing. Re-upload it."
            )
        source_bytes = storage.read_bytes(ctx.org_id, doc_row.source_path)
        facts = {
            **{k: v for k, v in variables.items() if isinstance(v, str)},
            "project_objective": context_summary or "",
            "meeting_notes": "",
        }
        built = await docx_proposal_service.build_docx_content(
            db, ctx,
            source_bytes=source_bytes, plan=doc_row.plan_json or {},
            variables=variables, line_items=line_items,
            total_amount=total, currency=currency, facts=facts,
        )
        content = built["content_md"]
        docx_bytes = built["docx"]
        filled_json = built["filled"]
        unfilled_placeholders = built["unfilled"]
    else:
        content = template_service.render(template.body_md, variables)

    proposal = Proposal(
        org_id=ctx.org_id,
        lead_id=lead_id,
        program_id=program_id,
        project_id=project_id,
        title=f"{program.name} Proposal — {lead.name}",
        template_id=template.id,
        template_version=template.version,
        pricing_table_id=pricing.id,
        pricing_version=pricing.version,
        content_md=content,
        variables=variables,
        line_items=line_items,
        total_amount=total,
        currency=currency,
        filled_json=filled_json,
        template_kind=getattr(template, "kind", "markdown"),
        created_by=ctx.user_id,
    )
    db.add(proposal)
    await db.flush()

    if docx_bytes is not None:
        from app.services import storage

        proposal.docx_path = storage.save_bytes(
            ctx.org_id, storage.CATEGORY_PROPOSALS,
            f"{program.name}_{lead.name}.docx", docx_bytes,
        )

    # F47, third gap: `[missing:...]` exists so "a human notices instead of
    # silently sending blanks" — but nothing ever looked. `missing_variables`
    # had zero callers, so a marker was born here, survived the whole review,
    # and reached a real client's PDF. It is caught at the approve gate now;
    # catching it at BIRTH is what makes it fixable rather than merely blocked.
    #
    # No content is invented to fill the gap: an unsupplied optional (typically
    # `context_summary`, which the assistant's `context_note` argument leaves
    # empty whenever the model omits it) stays visible and is escalated.
    unfilled = template_service.missing_variables(content)
    if unfilled:
        from app.core.constants import DecisionType
        from app.engines.common import record_decision

        logger.warning(
            "Proposal %s rendered with unfilled template variables: %s",
            proposal.id, ", ".join(sorted(set(unfilled))),
        )
        await record_decision(
            db, org_id=ctx.org_id, project_id=project_id,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine="document",
            decision="Proposal rendered with blanks", needs_human=True,
            confidence=1.0,
            reason=(
                f"Template '{template.name}' v{template.version} has no value for "
                f"{', '.join(sorted(set(unfilled)))}. The proposal reads "
                f"[missing:…] where those belong and must not go to the client "
                f"until they are filled in."
            ),
            input_summary=f"proposal={proposal.title}",
            entity_type="proposal", entity_id=proposal.id,
        )

    # A required placeholder the model would not ground is escalated exactly
    # like a [missing:...] marker (F47): the send gate refuses it, and a human
    # is told which section is blank rather than a plausible invention going
    # out.
    if unfilled_placeholders:
        from app.core.constants import DecisionType
        from app.engines.common import record_decision

        names = ", ".join(sorted(set(unfilled_placeholders)))
        logger.warning("Proposal %s has unfilled placeholders: %s", proposal.id, names)
        await record_decision(
            db, org_id=ctx.org_id, project_id=project_id,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine="document",
            decision="Proposal has unfilled sections", needs_human=True,
            confidence=1.0,
            reason=(
                f"The sections {names} could not be written from what is on "
                f"record, so they are blank in '{template.name}' "
                f"v{template.version}. Fill them in before this goes to the client."
            ),
            input_summary=f"proposal={proposal.title}",
            entity_type="proposal", entity_id=proposal.id,
        )

    await _save_revision(db, proposal, instruction="Initial draft", edited_by=ctx.user_id)
    await audit_service.record(
        db,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        action="proposal.created",
        entity_type="proposal",
        entity_id=proposal.id,
        detail={"lead_id": lead_id, "program_id": program_id, "total": total},
    )
    return proposal


async def mark_sent(
    db: AsyncSession, proposal: Proposal, *, message_id: str | None = None
) -> None:
    """Record the send and walk the deal forward: proposal out →
    projects.status planning → proposal_stage (Workflow 3.7). Idempotent —
    safe to call from both the approve-send tap and the send worker."""
    from app.models.project import Project

    if proposal.status != ProposalStatus.SENT.value:
        proposal.status = ProposalStatus.SENT.value
        proposal.sent_at = utcnow()
    if message_id and not proposal.sent_message_id:
        proposal.sent_message_id = message_id
    if proposal.project_id:
        project = (
            await db.execute(
                select(Project).where(
                    Project.id == proposal.project_id,
                    Project.org_id == proposal.org_id,
                )
            )
        ).scalar_one_or_none()
        if project is not None and project.status == "planning":
            project.status = "proposal_stage"
            from app.core.constants import EventType
            from app.engines import events as event_stream

            await event_stream.emit(
                db, org_id=proposal.org_id,
                event_type=EventType.PROJECT_STATUS_CHANGED.value,
                project_id=project.id, entity_type="project", entity_id=project.id,
                details={"from": "planning", "to": "proposal_stage",
                         "why": "proposal sent"},
            )


async def get_proposal(db: AsyncSession, org_id: str, proposal_id: str) -> Proposal:
    proposal = (
        await db.execute(
            select(Proposal).where(Proposal.id == proposal_id, Proposal.org_id == org_id)
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise NotFoundError("Proposal not found")
    return proposal


async def _save_revision(
    db: AsyncSession, proposal: Proposal, *, instruction: str | None, edited_by: str | None
) -> None:
    count = (
        await db.execute(
            select(func.count(ProposalRevision.id)).where(
                ProposalRevision.proposal_id == proposal.id
            )
        )
    ).scalar_one()
    db.add(
        ProposalRevision(
            org_id=proposal.org_id,
            proposal_id=proposal.id,
            revision_no=count + 1,
            instruction=instruction,
            content_md=proposal.content_md,
            line_items=proposal.line_items,
            total_amount=proposal.total_amount,
            edited_by=edited_by,
        )
    )


def apply_line_item_ops(
    proposal: Proposal, operations: list[dict[str, Any]]
) -> list[str]:
    """Apply structured commercial edits. Numbers come from the pricing table
    or an explicit human instruction — never invented by the model.

    Supported ops:
      {"op": "set_quantity",   "code": "workshop", "quantity": 16}
      {"op": "set_unit_price", "code": "workshop", "unit_price": 1500}   (human-directed)
      {"op": "remove_item",    "code": "kit"}
      {"op": "add_item",       "code": "kit", "label": "...", "unit": "...",
                               "unit_price": 500, "quantity": 2}
    Returns human-readable change notes.
    """
    notes: list[str] = []
    items = [dict(i) for i in (proposal.line_items or [])]

    def _find(code: str) -> dict[str, Any] | None:
        for i in items:
            if (i.get("code") or "").lower() == (code or "").lower():
                return i
        return None

    for op in operations:
        kind = op.get("op")
        code = op.get("code", "")
        if kind == "set_quantity":
            item = _find(code)
            if item is None:
                raise ValidationFailedError(f"No line item with code '{code}'")
            item["quantity"] = float(op["quantity"])
            notes.append(f"quantity of '{item['label']}' set to {int(float(op['quantity']))}")
        elif kind == "set_unit_price":
            item = _find(code)
            if item is None:
                raise ValidationFailedError(f"No line item with code '{code}'")
            item["unit_price"] = float(op["unit_price"])
            notes.append(f"unit price of '{item['label']}' set to {op['unit_price']}")
        elif kind == "remove_item":
            item = _find(code)
            if item is None:
                raise ValidationFailedError(f"No line item with code '{code}'")
            items.remove(item)
            notes.append(f"removed '{item['label']}'")
        elif kind == "add_item":
            if _find(code) is not None:
                raise ValidationFailedError(f"Line item '{code}' already exists")
            items.append(
                {
                    "code": code,
                    "label": op.get("label", code),
                    "unit": op.get("unit", "-"),
                    "unit_price": float(op.get("unit_price", 0) or 0),
                    "quantity": float(op.get("quantity", 1) or 1),
                }
            )
            notes.append(f"added '{op.get('label', code)}'")
        else:
            raise ValidationFailedError(f"Unknown edit operation '{kind}'")

    total = compute_totals(items)
    proposal.line_items = items
    proposal.total_amount = total
    variables = dict(proposal.variables or {})
    variables["total_amount"] = _money(total, proposal.currency)
    block = render_pricing_block(items, proposal.currency)
    variables["pricing_table"] = block
    proposal.variables = variables
    proposal.content_md = replace_pricing_block(proposal.content_md, block)
    return notes


# Currency markers and price words that put a number in a "this is money"
# context. Re-inserting the machine table protects the TABLE, but a model told
# to "apply a 10% discount" writes the discounted figures into the PROSE, which
# survives re-insertion (finding F23). A prompt rule ("do NOT change prices")
# did not hold on any model tested — so this fence is deterministic.
_MONEY_MARKERS = ("rs", "₹", "inr", "usd", "eur", "$")
_PRICE_WORDS = (
    "per ", "price", "cost", "fee", "total", "discount", "rate", "charge",
    "amount", "invest", "each", "subtotal", "quote", "pricing", "sum",
)
# Comma-grouped (1,305 / 218,700) or plain (1305) numbers, optional decimals.
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _allowed_amounts(line_items: list[dict[str, Any]] | None, total: Any) -> set[float]:
    """Every number that may legitimately appear in the prose: each unit price,
    quantity, line total, and the grand total."""
    allowed: set[float] = set()

    def add(value: Any) -> None:
        try:
            allowed.add(round(float(value), 2))
        except (TypeError, ValueError):
            pass

    for item in line_items or []:
        add(item.get("unit_price"))
        add(item.get("quantity"))
        qty = float(item.get("quantity", 0) or 0)
        price = float(item.get("unit_price", 0) or 0)
        add(round(qty * price, 2))
        add(item.get("line_total"))
    add(total)
    return allowed


def narrative_price_drift(proposal: Proposal, new_content_md: str) -> list[str]:
    """Money-shaped numbers in the rewritten PROSE that are not in the proposal's
    locked commercials. The machine-replaced pricing block is excluded (its
    numbers are about to be overwritten). Returns the offending literals, in
    order, de-duplicated — empty when the wording is clean."""
    text = new_content_md
    start, end = text.find(PRICING_START), text.find(PRICING_END)
    if start != -1 and end != -1 and end > start:
        text = text[:start] + text[end + len(PRICING_END):]

    allowed = _allowed_amounts(proposal.line_items, proposal.total_amount)
    low = text.lower()
    drift: list[str] = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0)
        value = float(raw.replace(",", ""))
        if value < 100:  # quantities, list markers, small counts — never a price here
            continue
        if round(value, 2) in allowed:
            continue
        if 1900 <= value <= 2100 and "," not in raw and "." not in raw:
            continue  # a bare year, not money
        window = low[max(0, match.start() - 16):min(len(low), match.end() + 16)]
        if any(m in window for m in _MONEY_MARKERS) or any(w in window for w in _PRICE_WORDS):
            if raw not in drift:
                drift.append(raw)
    return drift


def apply_narrative_edit(proposal: Proposal, new_content_md: str) -> None:
    """Accept LLM-rewritten narrative but forcibly re-insert the computed
    commercial block so document numbers cannot drift from the stored ones —
    AND reject a rewrite that smuggled a different price into the prose (F23),
    validating BEFORE any mutation so a rejected edit leaves the proposal
    untouched."""
    drift = narrative_price_drift(proposal, new_content_md)
    if drift:
        raise ValidationFailedError(
            "This rewrite put prices into the wording that are not in the locked "
            f"commercial table ({', '.join(drift[:5])}). The AI cannot change "
            "prices by rewording — to change the commercials, edit the pricing "
            "table itself. Nothing was changed."
        )
    block = render_pricing_block(proposal.line_items or [], proposal.currency)
    proposal.content_md = replace_pricing_block(new_content_md, block)


async def record_edit(
    db: AsyncSession,
    ctx: OrgContext,
    proposal: Proposal,
    *,
    instruction: str,
) -> None:
    proposal.docx_path = None  # rendered files are stale after an edit
    proposal.pdf_path = None
    await _save_revision(db, proposal, instruction=instruction, edited_by=ctx.user_id)
    await audit_service.record(
        db,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        action="proposal.edited",
        entity_type="proposal",
        entity_id=proposal.id,
        detail={"instruction": instruction, "total": proposal.total_amount},
    )
