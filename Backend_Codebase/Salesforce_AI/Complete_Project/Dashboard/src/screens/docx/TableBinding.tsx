/**
 * Mapping one of the document's tables onto the rate card — Task 21 Step 2.
 *
 * The numbers never come from the model: they come from the locked
 * `PricingTable` version, exactly as `compute_totals` produces them today. This
 * dialog only says which of the document's own columns each one is written
 * into, so the table keeps its borders, shading and fonts — `fill_table` clones
 * the document's own first body row as the template for every generated row.
 *
 * Two behaviours here are not obvious and are stated on screen rather than
 * discovered in a client's document:
 *
 * - **An unmapped column is emptied, not left alone.** `fill_table` writes ""
 *   into every cell whose index is not in `columns`.
 * - **The total is written into the last row**, and only its value. The
 *   wording beside it is the organisation's own and is kept.
 *
 * The `Modal` primitive has no dismiss behaviour by design (D18) — no escape
 * key, no click-out — so Cancel is the only way back and is always present.
 */
import { useState } from "react";

import type { Block } from "../../api/reads";
import {
  Banner,
  Button,
  DataTable,
  Field,
  Modal,
  Select,
  TextInput,
  styles as s,
} from "../../ui/primitives";
import c from "./docx.module.css";
import {
  TABLE_FIELDS,
  maxHeaderRows,
  tableMappingFor,
  tableMappingProblems,
  tablePreviewRows,
  tablePreviewTotal,
  type Plan,
  type TableMapping,
} from "./plan";

const FIELD_LABEL: Record<string, string> = {
  label: "label — what the item is called",
  unit: "unit — what it is priced by",
  unit_price: "unit price",
  quantity: "quantity",
  line_total: "line total",
};

const FIELD_OPTIONS = TABLE_FIELDS.map((f) => ({ value: f, label: FIELD_LABEL[f] }));

export function TableBinding({
  block,
  plan,
  onSave,
  onClear,
  onCancel,
}: {
  block: Block;
  plan: Plan;
  onSave: (mapping: TableMapping) => void;
  onClear: () => void;
  onCancel: () => void;
}) {
  const table = block.table;
  const existing = tableMappingFor(plan, block.path);
  const cols = table?.cols ?? 0;

  // One entry per column of the real table, so the controls line up with what
  // the administrator is looking at. Empty means "not mapped".
  const [fields, setFields] = useState<string[]>(() => {
    const initial = Array.from({ length: cols }, () => "");
    for (const col of existing?.columns ?? []) {
      if (col.col >= 0 && col.col < cols) initial[col.col] = col.field;
    }
    return initial;
  });
  const [headerRows, setHeaderRows] = useState(existing?.header_rows ?? 1);
  const [hasTotal, setHasTotal] = useState(existing?.total_row != null);
  const [valueCol, setValueCol] = useState(existing?.total_row?.value_col ?? cols - 1);

  if (!table) return null;

  const columns = fields
    .map((field, col) => ({ col, field }))
    .filter((x) => x.field !== "");

  // `label_col` is required by `fill.apply`, which reads it straight out of the
  // entry, but `fill_table` never uses it: a total row keeps the document's own
  // wording and only its value is written. So it is derived rather than asked
  // for — asking would be asking for something that does nothing.
  const labelCol = columns.find((x) => x.field === "label")?.col ?? 0;

  const mapping: TableMapping = {
    columns,
    header_rows: headerRows,
    total_row: hasTotal ? { label_col: labelCol, value_col: valueCol } : null,
  };
  const problems = tableMappingProblems(mapping, block);
  const max = maxHeaderRows(table.rows, hasTotal);
  const preview = tablePreviewRows(mapping, block);

  function setField(col: number, field: string) {
    setFields(fields.map((f, i) => (i === col ? field : f)));
  }

  const columnName = (i: number) => table.header[i]?.trim() || `Column ${i + 1}`;
  const colOptions = Array.from({ length: cols }, (_, i) => ({
    value: String(i),
    label: columnName(i),
  }));

  return (
    <Modal title={`The table at ${block.path}`}>
      <p className={c.caption}>
        {`${table.rows} rows, ${cols} columns. The rate card supplies the rows; ` +
          "this says which column each value is written into. Everything else " +
          "about the table — its borders, shading and fonts — comes from the " +
          "document."}
      </p>

      <div className={c.tableScroll}>
        <table className={c.docTable}>
          <thead>
            <tr>
              {table.sample[0]?.map((cell, i) => (
                <th key={i} scope="col">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.sample.slice(1).map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={c.caption}>The document&rsquo;s own rows, as uploaded.</p>

      <div className={c.stack}>
        <DataTable
          columns={["Column in the document", "Filled with"]}
          rows={fields.map((field, col) => [
            <span className={c.literalCell}>{columnName(col)}</span>,
            <Select
              aria-label={`Rate-card field for ${columnName(col)}`}
              placeholder="Left empty"
              options={FIELD_OPTIONS}
              value={field}
              onChange={(e) => setField(col, e.target.value)}
            />,
          ])}
        />
        <p className={c.caption}>
          A column left empty is <strong>cleared</strong> in every generated row.
          The rows the rate card supplies replace the table&rsquo;s body entirely,
          so a column with nothing mapped to it has nothing to show.
        </p>
      </div>

      <div className={c.stack}>
        <Field
          label="Header rows kept as they are"
          htmlFor="docx-header-rows"
          caption={`at most ${max} for this table — the first row after them is cloned as the template for every generated row`}
        >
          <TextInput
            id="docx-header-rows"
            type="number"
            min={0}
            max={Math.max(max, 0)}
            value={headerRows}
            onChange={(e) => setHeaderRows(Number(e.target.value))}
          />
        </Field>

        <Field label="The last row is a total" htmlFor="docx-total-row">
          <input
            id="docx-total-row"
            type="checkbox"
            checked={hasTotal}
            onChange={(e) => setHasTotal(e.target.checked)}
          />
        </Field>

        {hasTotal && (
          <Field
            label="Column the total is written into"
            htmlFor="docx-total-col"
            caption="only the value is written; the wording beside it is the document's own and is kept"
          >
            <Select
              id="docx-total-col"
              options={colOptions}
              value={String(valueCol)}
              onChange={(e) => setValueCol(Number(e.target.value))}
            />
          </Field>
        )}
      </div>

      <div className={c.stack}>
        <p className={c.caption}>
          What a proposal would show, against two made-up items. The figures are
          grouped but carry no currency symbol: that comes from the rate card,
          which this screen has not read.
        </p>
        <div className={c.tableScroll}>
          <table className={c.docTable}>
            <thead>
              <tr>
                {Array.from({ length: cols }, (_, i) => (
                  <th key={i} scope="col">
                    {columnName(i)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{cell}</td>
                  ))}
                </tr>
              ))}
              {hasTotal && (
                <tr>
                  {/* Verified against body[89] of School_YuviPep 360_2 1.docx:
                      the total row keeps every cell the document already had
                      and only the value column is written. Blanks here would
                      say the opposite. */}
                  {Array.from({ length: cols }, (_, i) => (
                    <td key={i}>
                      {i === valueCol ? (
                        tablePreviewTotal()
                      ) : (
                        <span className={s.muted}>unchanged</span>
                      )}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {hasTotal && (
          <p className={c.caption}>
            The last row is shown with only its value written — its wording stays
            as the document has it.
          </p>
        )}
      </div>

      {problems.length > 0 && (
        <div className={c.stack}>
          <Banner tone="blocked" title="This mapping cannot be saved yet">
            <ul className={c.problems}>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </Banner>
        </div>
      )}

      <div className={`${c.actions} ${c.stack}`}>
        <Button
          variant="primary"
          disabled={problems.length > 0}
          onClick={() => onSave(mapping)}
        >
          Save this mapping
        </Button>
        {existing && (
          <Button variant="danger" onClick={onClear}>
            Remove the mapping
          </Button>
        )}
        <Button variant="quiet" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      <p className={`${s.muted} ${c.caption}`}>
        Nothing is sent yet. The plan is saved from the editor behind this
        dialog.
      </p>
    </Modal>
  );
}
