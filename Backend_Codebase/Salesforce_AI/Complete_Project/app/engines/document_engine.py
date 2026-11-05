"""Document Engine — builds every artifact; accepts manual uploads as equals
(30-Workflows §4 engine 6).

Prices come from pricing_tables only, or from a recorded human approval —
the AI writes the words around the numbers, never the numbers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.core.constants import (
    DeliverableSource,
    DeliverableStatus,
    EventType,
    InvoiceKind,
    InvoiceStatus,
    ProposalStatus,
)
from app.engines import events, nlu
from app.models.finance import Deliverable, Invoice, Payment
from app.models.project import Project
from app.models.proposal import Proposal
from app.services.proposal_service import compute_totals

logger = logging.getLogger(__name__)

ENGINE = "document"


# ─────────────────────────────────────────────────────────────────────────────
# Deliverables — generated or uploaded, both first-class
# ─────────────────────────────────────────────────────────────────────────────


async def next_version(db: AsyncSession, *, project_id: str, dtype: str) -> int:
    current = (
        await db.execute(
            select(func.max(Deliverable.version)).where(
                Deliverable.project_id == project_id, Deliverable.type == dtype
            )
        )
    ).scalar_one()
    return (current or 0) + 1


async def add_deliverable(
    db: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    dtype: str,
    title: str | None = None,
    content_md: str | None = None,
    file_path: str | None = None,
    source: str = DeliverableSource.AI_GENERATED.value,
    uploaded_by: str | None = None,
    linked_action_item_id: str | None = None,
    status: str = DeliverableStatus.DRAFT.value,
    actor: str = "ai",
) -> Deliverable:
    """One new version of one artifact. A person's upload counts exactly the
    same as a generated file — the source field records which."""
    row = Deliverable(
        org_id=org_id,
        project_id=project_id,
        type=dtype,
        title=title,
        content_md=content_md,
        file_path=file_path,
        version=await next_version(db, project_id=project_id, dtype=dtype),
        source=source,
        uploaded_by=uploaded_by,
        status=status,
        linked_action_item_id=linked_action_item_id,
    )
    db.add(row)
    await db.flush()
    await events.emit(
        db, org_id=org_id, event_type=EventType.DELIVERABLE_ADDED.value,
        project_id=project_id, entity_type="deliverable", entity_id=row.id,
        actor=uploaded_by or actor,
        details={"type": dtype, "version": row.version, "source": source},
    )
    return row


async def latest_deliverable(
    db: AsyncSession, *, project_id: str, dtype: str
) -> Deliverable | None:
    return (
        await db.execute(
            select(Deliverable)
            .where(Deliverable.project_id == project_id, Deliverable.type == dtype)
            .order_by(Deliverable.version.desc())
        )
    ).scalars().first()


async def generate_text_artifact(
    *,
    org_id: str,
    dtype: str,
    title: str,
    context: dict[str, Any],
    instruction: str | None = None,
) -> str:
    """Draft an artifact's text. LLM when available; otherwise an honest
    structured assembly of the real data it was given (never invented)."""
    if nlu.llm_available():
        try:
            from app.ai.llm import get_model_layer

            resp = await get_model_layer().generate(
                purpose=f"document.{dtype}",
                org_id=org_id,
                tier="strong",
                system=(
                    # F31 / same class as F4 and F11: naming an industry here
                    # makes the model write in that industry's vocabulary
                    # whatever the client actually is — and this file is where
                    # invoices and deliverables get built.
                    "You write clear, warm, factual documents on behalf of an "
                    "organisation for its clients. Use ONLY the facts provided; "
                    "never invent numbers, prices or dates, and never assume an "
                    "industry or type of organisation that the facts do not state."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Write the {dtype} titled '{title}'.\n"
                        + (f"Instruction: {instruction}\n" if instruction else "")
                        + "Facts:\n"
                        + "\n".join(f"- {k}: {v}" for k, v in context.items())
                    ),
                }],
            )
            if resp.text.strip():
                return resp.text.strip()
        except Exception:  # noqa: BLE001
            logger.exception("LLM artifact generation failed; using assembly")
    lines = [f"# {title}", ""]
    if instruction:
        lines += [f"_{instruction}_", ""]
    for key, value in context.items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, list):
            lines.append(f"## {label}")
            lines += [f"- {v}" for v in value]
            lines.append("")
        else:
            lines.append(f"**{label}:** {value}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Proposal amendments (scope changes) — Workflow 20
# ─────────────────────────────────────────────────────────────────────────────


async def accepted_proposal(db: AsyncSession, *, org_id: str, project_id: str) -> Proposal | None:
    return (
        await db.execute(
            select(Proposal)
            .where(
                Proposal.org_id == org_id,
                Proposal.project_id == project_id,
                Proposal.status == ProposalStatus.ACCEPTED.value,
                Proposal.amends_proposal_id.is_(None),
            )
            .order_by(Proposal.created_at.desc())
        )
    ).scalars().first()


async def accepted_total(db: AsyncSession, *, org_id: str, project_id: str) -> tuple[float, str]:
    """Accepted proposal total + accepted amendments — with the computation."""
    rows = (
        await db.execute(
            select(Proposal).where(
                Proposal.org_id == org_id,
                Proposal.project_id == project_id,
                Proposal.status == ProposalStatus.ACCEPTED.value,
            )
        )
    ).scalars().all()
    base = [p for p in rows if not p.amends_proposal_id]
    amendments = [p for p in rows if p.amends_proposal_id]
    total = sum(p.total_amount for p in base) + sum(p.total_amount for p in amendments)
    parts = [f"{p.total_amount:,.0f} (accepted proposal)" for p in base]
    parts += [f"{p.total_amount:,.0f} (amendment)" for p in amendments]
    return total, " + ".join(parts) if parts else "0"


async def build_amendment(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    base_proposal: Proposal,
    delta_line_items: list[dict[str, Any]],
    reason: str,
    created_by: str,
    special_price_approval_id: str | None = None,
) -> Proposal:
    """A proposal amendment referencing the accepted one: old total, addition,
    new total. Line items are computed by the caller strictly from
    pricing_tables (or the recorded special-price approval)."""
    delta_total = compute_totals(delta_line_items)
    new_total = base_proposal.total_amount + delta_total
    content = (
        f"# Amendment to: {base_proposal.title}\n\n"
        f"**Reason:** {reason}\n\n"
        f"| | Amount ({base_proposal.currency}) |\n|---|---|\n"
        f"| Accepted proposal | {base_proposal.total_amount:,.0f} |\n"
        f"| This amendment | {delta_total:+,.0f} |\n"
        f"| **New total** | **{new_total:,.0f}** |\n"
    )
    amendment = Proposal(
        org_id=org_id,
        lead_id=base_proposal.lead_id,
        program_id=base_proposal.program_id,
        project_id=project.id,
        title=f"Amendment — {base_proposal.title}",
        status=ProposalStatus.DRAFT.value,
        template_id=base_proposal.template_id,
        template_version=base_proposal.template_version,
        pricing_table_id=base_proposal.pricing_table_id,
        pricing_version=base_proposal.pricing_version,
        content_md=content,
        variables=dict(base_proposal.variables or {}),
        line_items=delta_line_items,
        total_amount=delta_total,
        currency=base_proposal.currency,
        created_by=created_by,
        amends_proposal_id=base_proposal.id,
        special_price_approval_id=special_price_approval_id,
    )
    db.add(amendment)
    await db.flush()
    return amendment


# ─────────────────────────────────────────────────────────────────────────────
# Invoices — amounts always derived, never typed (Data Model §6.8)
# ─────────────────────────────────────────────────────────────────────────────


async def payments_received(db: AsyncSession, *, org_id: str, project_id: str) -> float:
    invoice_ids = (
        await db.execute(
            select(Invoice.id).where(
                Invoice.org_id == org_id, Invoice.project_id == project_id
            )
        )
    ).scalars().all()
    if not invoice_ids:
        return 0.0
    return (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.invoice_id.in_(invoice_ids)
            )
        )
    ).scalar_one()


async def create_invoice(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    kind: str,
    advance_pct: float = 50.0,
    due_in_days: int = 14,
    sent_to_stakeholder_id: str | None = None,
) -> Invoice:
    """advance = pct of the accepted total; balance = accepted total (incl.
    amendments) minus everything already received; full = the whole total."""
    total, computation = await accepted_total(db, org_id=org_id, project_id=project.id)
    received = await payments_received(db, org_id=org_id, project_id=project.id)
    if kind == InvoiceKind.ADVANCE.value:
        amount = round(total * advance_pct / 100.0, 2)
        computation = f"{advance_pct:.0f}% of ({computation}) = {amount:,.0f}"
    elif kind == InvoiceKind.BALANCE.value:
        amount = round(total - received, 2)
        computation = f"({computation}) − {received:,.0f} received = {amount:,.0f}"
    else:
        amount = round(total, 2)
        computation = f"{computation} = {amount:,.0f}"
    invoice = Invoice(
        org_id=org_id,
        project_id=project.id,
        kind=kind,
        amount=amount,
        currency=project.currency or "INR",
        computation=computation,
        due_date=utcnow() + timedelta(days=due_in_days),
        status=InvoiceStatus.DRAFT.value,
        sent_to_stakeholder_id=sent_to_stakeholder_id,
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def record_payment(
    db: AsyncSession,
    *,
    org_id: str,
    invoice: Invoice,
    amount: float,
    method: str | None,
    recorded_by: str,
    note: str | None = None,
    received_on: datetime | None = None,
) -> Payment:
    """Part-payments are simply multiple rows; invoice status is recomputed."""
    payment = Payment(
        org_id=org_id,
        invoice_id=invoice.id,
        amount=amount,
        method=method,
        recorded_by=recorded_by,
        note=note,
        received_on=received_on or utcnow(),
    )
    db.add(payment)
    await db.flush()
    paid = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.invoice_id == invoice.id
            )
        )
    ).scalar_one()
    invoice.status = (
        InvoiceStatus.PAID.value if paid >= invoice.amount - 0.01
        else InvoiceStatus.PART_PAID.value
    )
    await events.emit(
        db, org_id=org_id, event_type=EventType.PAYMENT_RECEIVED.value,
        project_id=invoice.project_id, entity_type="invoice", entity_id=invoice.id,
        actor=recorded_by,
        details={"amount": amount, "invoice_status": invoice.status},
    )
    return payment


# ─────────────────────────────────────────────────────────────────────────────
# Coverage check — a reply must answer every extracted point, or say why not
# ─────────────────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "for", "and", "or", "to", "of", "in", "on", "at", "is",
    "it", "this", "that", "with", "please", "days", "day",
}


def _keywords(text: str) -> set[str]:
    return {
        w.strip(".,!?;:()\"'").lower()
        for w in text.split()
        if len(w) > 3 and w.lower() not in _STOPWORDS
    }


def coverage_check(draft_text: str, extracted_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns the points NOT clearly addressed by the draft/document.

    The AI checks completeness — it never blocks the human (Workflow 4 B.4)."""
    uncovered: list[dict[str, Any]] = []
    draft_words = _keywords(draft_text)
    for point in extracted_points or []:
        detail = str(point.get("detail") or point.get("type") or "")
        want = _keywords(detail)
        if not want:
            continue
        overlap = len(want & draft_words) / len(want)
        if overlap < 0.34:
            uncovered.append(point)
    return uncovered
