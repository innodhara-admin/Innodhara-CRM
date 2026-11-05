/**
 * The placeholder editor — Task 20 Step 4, spec §11.
 *
 * This screen decides what a proposal built from this template will say, and it
 * does so by editing a *plan*, never the document. The uploaded file is stored
 * once and never rewritten: generation is `source.docx + plan + values -> a new
 * file`, which is the whole reason a branded document survives the process.
 *
 * Three things on this screen are easy to get subtly wrong, so each is stated
 * where the operator can see it rather than left to be discovered:
 *
 * - **Suggesting costs a model call.** The button says so before it is pressed.
 * - **Preview renders the SAVED plan.** `preview_proposal_template` reads
 *   `doc_row.plan_json`, so unsaved chips are not in it. With unsaved changes
 *   the screen says that instead of showing a PDF that quietly disagrees with
 *   what is on screen.
 * - **Leaving loses unsaved work.** Nothing here autosaves — a half-marked
 *   template that saved itself would be a template that generates half a
 *   proposal.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { request } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import { TemplateDocRead, type Block } from "../../api/reads";
import { useSession } from "../../session/store";
import { ReadError, Section, asApiError } from "../../ui/ItemScreen";
import {
  Banner,
  Button,
  Masthead,
  Panel,
  Shell,
  styles as s,
} from "../../ui/primitives";
import { DriftBanner, SessionBar } from "../../ui/SessionBar";
import { BlockFlow, TemplateImages } from "./BlockFlow";
import { fetchBinary, openInNewTab } from "./binary";
import c from "./docx.module.css";
import { SuggestionChip } from "./SuggestionChip";
import { TableBinding } from "./TableBinding";
import { TokenPanel } from "./TokenPanel";
import {
  acceptSuggestion,
  addInsert,
  anchorOf,
  entriesForBlock,
  moveEntry,
  clearTableMapping,
  planProblems,
  rejectSuggestion,
  setTableMapping,
  tableMappingFor,
  updateBrief,
  usableSuggestions,
  type Plan,
  type Suggestion,
  type TableMapping,
} from "./plan";

/** What the backend detected about the contents page, said in words. */
const INDEX_NOTE: Record<string, string> = {
  static:
    "The contents page is plain text, so its page numbers are recalculated " +
    "each time a proposal is produced.",
  field:
    "The contents page is a Word field; Word refreshes it when the file is " +
    "opened.",
  none: "This document has no contents page.",
};

export function DocxEditor() {
  const navigate = useNavigate();
  const { org } = useSession();
  const { docId = "" } = useParams();

  const doc = useQuery({
    queryKey: ["templateDoc", docId],
    enabled: Boolean(org) && Boolean(docId),
    queryFn: () => request(endpoints.templateDoc(docId), { as: "org", shape: TemplateDocRead }),
  });

  const [plan, setPlan] = useState<Plan | null>(null);
  const [savedJson, setSavedJson] = useState<string>("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [busy, setBusy] = useState<"" | "suggest" | "save" | "preview">("");
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saved, setSaved] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; opened: boolean } | null>(null);
  const [leaving, setLeaving] = useState(false);
  /** The table block whose column mapping is open, if any. */
  const [mapping, setMapping] = useState<Block | null>(null);

  // The plan arrives with the document and is then owned by this screen.
  //
  // Seeded ONCE per document, guarded by a ref rather than by `plan === null`.
  // react-query refetches on reconnect by default, and a refetch hands back a
  // new `data` object; without the guard a network blip part-way through
  // marking a template would silently replace the operator's work with the
  // server's copy, and the screen would look like it had simply forgotten.
  const seeded = useRef<string | null>(null);
  useEffect(() => {
    if (!doc.data || seeded.current === doc.data.id) return;
    seeded.current = doc.data.id;
    const fromServer = doc.data.plan as unknown as Plan;
    setPlan(fromServer);
    setSavedJson(JSON.stringify(fromServer));
  }, [doc.data]);

  const blocks: readonly Block[] = doc.data?.outline.blocks ?? [];
  const dirty = plan !== null && JSON.stringify(plan) !== savedJson;

  // Covers a refresh, a close and a typed URL. In-app navigation off this
  // screen is only ever the rail's own buttons, which ask below.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const occurrences = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of doc.data?.outline.tokens ?? []) map.set(t.literal, t.occurrences);
    return map;
  }, [doc.data]);

  const placedKeys = useMemo(
    () => new Set((plan?.entries ?? []).map((e) => e.key)),
    [plan],
  );

  function edit(next: Plan) {
    setPlan(next);
    setProblems([]);
    setSaved(null);
  }

  /**
   * Removing a placed placeholder drops the suggestion it came from too.
   * Without that it is filtered out of `placed` and immediately reappears in
   * `pending` one line lower, which reads as the Remove button having failed.
   */
  function drop(key: string) {
    if (plan) edit(rejectSuggestion(plan, key));
    setSuggestions((current) => current.filter((x) => x.key !== key));
  }

  async function runSuggest() {
    setBusy("suggest");
    setError(null);
    try {
      const reply = await request(endpoints.templateDocSuggest(docId), {
        as: "org",
        method: "POST",
      });
      setSuggestions(usableSuggestions(reply, blocks));
    } catch (err) {
      setError(asApiError(err)?.detail ?? String(err));
    } finally {
      setBusy("");
    }
  }

  async function savePlan() {
    if (!plan) return;
    setBusy("save");
    setError(null);
    setProblems([]);
    try {
      await request(endpoints.templateDocPlan(docId), {
        as: "org",
        method: "PUT",
        body: { plan },
      });
      setSavedJson(JSON.stringify(plan));
      setSaved(
        `Saved. ${plan.entries.length} placeholder(s) are marked in this template.`,
      );
    } catch (err) {
      const api = asApiError(err);
      // 422 is validate_plan's list, joined into one message by the route.
      if (api && api.status === 422) setProblems(planProblems(api.detail));
      else setError(api?.detail ?? String(err));
    } finally {
      setBusy("");
    }
  }

  async function runPreview() {
    setBusy("preview");
    setError(null);
    try {
      const blob = await fetchBinary(endpoints.templateDocPreview(docId), "POST");
      setPreview(openInNewTab(blob));
    } catch (err) {
      setError(asApiError(err)?.detail ?? String(err));
    } finally {
      setBusy("");
    }
  }

  function addAfter(path: string) {
    if (!plan) return;
    try {
      edit(addInsert(plan, path, null, blocks));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function chipsFor(block: Block) {
    if (!plan) return null;
    const placed = entriesForBlock(plan, block.path);
    const pending = suggestions.filter(
      (sg) => anchorOf(sg) === block.path && !placedKeys.has(sg.key),
    );
    const mapped = block.kind === "table" ? tableMappingFor(plan, block.path) : null;
    if (placed.length === 0 && pending.length === 0 && block.kind !== "table") {
      return null;
    }
    return (
      <>
        {block.kind === "table" && (
          <div className={c.chipActions}>
            <Button variant="quiet" onClick={() => setMapping(block)}>
              {mapped
                ? `Edit the column mapping (${mapped.columns.length} mapped)`
                : "Map this table to the rate card"}
            </Button>
          </div>
        )}
        {placed.map((entry) => (
          <SuggestionChip
            key={entry.key}
            entry={entry}
            state="placed"
            occurrences={entry.literal ? occurrences.get(entry.literal) : undefined}
            canMoveUp={moveEntry(plan, entry.key, "up", blocks) !== plan}
            canMoveDown={moveEntry(plan, entry.key, "down", blocks) !== plan}
            onAccept={(next) => edit(acceptSuggestion(plan, next))}
            onReject={drop}
            onBrief={(key, brief) => edit(updateBrief(plan, key, brief))}
            onMove={(key, direction) => edit(moveEntry(plan, key, direction, blocks))}
          />
        ))}
        {pending.map((sg) => (
          <SuggestionChip
            key={sg.key}
            entry={sg}
            state="suggested"
            confidence={sg.confidence}
            why={sg.why}
            occurrences={sg.literal ? occurrences.get(sg.literal) : undefined}
            canMoveUp={false}
            canMoveDown={false}
            onAccept={(next) => edit(acceptSuggestion(plan, next))}
            onReject={(key) => setSuggestions(suggestions.filter((x) => x.key !== key))}
            onBrief={() => undefined}
            onMove={() => undefined}
          />
        ))}
      </>
    );
  }

  // Tokens have no position in the flow, and the token panel below is where
  // they are read and bound. What is left here is the case that has a position
  // and cannot be shown at it: an entry whose block is not in this outline,
  // which save will refuse by name.
  const stranded = (plan?.entries ?? []).filter((e) => {
    const anchor = anchorOf(e);
    return anchor !== null && !blocks.some((b) => b.path === anchor);
  });
  const tokenSuggestions = suggestions.filter(
    (sg) => sg.kind === "token" && !placedKeys.has(sg.key),
  );

  return (
    <Shell
      rail={
        <>
          <Masthead />
          <SessionBar />
          <hr className={s.ruleBreak} />
          <Button
            variant="quiet"
            onClick={() => (dirty ? setLeaving(true) : navigate("/checklist"))}
          >
            Back to the checklist
          </Button>
        </>
      }
    >
      <DriftBanner />

      {!org ? (
        <Panel eyebrow="No session" title="Sign in to continue">
          <Banner tone="warn" title="No organisation session">
            <p style={{ margin: 0 }}>
              A template belongs to one organisation, and this screen reads it
              with that organisation&rsquo;s token.
            </p>
          </Banner>
        </Panel>
      ) : doc.isError ? (
        <ReadError error={doc.error} what="this uploaded document" />
      ) : !doc.data || !plan ? (
        <Panel eyebrow="Item 6" title="Word document template">
          <p className={s.muted}>Reading the document…</p>
        </Panel>
      ) : (
        <>
          <Panel
            eyebrow={`Item 6 · version ${doc.data.version}`}
            title={doc.data.name || doc.data.filename}
          >
            <p className={c.factList}>
              <span>{doc.data.filename}</span>
              <span>{`${Math.round(doc.data.size_bytes / 1024)} KB`}</span>
              <span>{`${blocks.length} blocks`}</span>
              <span>{`${doc.data.outline.media.length} images`}</span>
              <span>{`${plan.entries.length} placeholders`}</span>
              <span>{`index: ${doc.data.index_kind}`}</span>
            </p>
            <p style={{ maxInlineSize: "var(--measure)", marginBlockEnd: 0 }}>
              {INDEX_NOTE[doc.data.index_kind]}
            </p>
            {doc.data.analysis_status !== "ready" && (
              <div className={c.stack}>
                <Banner
                  tone="blocked"
                  title="This document was not fully read"
                  serverMessage={doc.data.analysis_error ?? undefined}
                >
                  <p style={{ margin: 0 }}>
                    {`Its analysis status is “${doc.data.analysis_status}”. Marking ` +
                      "placeholders against a partial outline would place them " +
                      "at positions that may not be there. Upload it again."}
                  </p>
                </Banner>
              </div>
            )}
          </Panel>

          <Section title="What the system fills in" eyebrow="Placeholders">
            <div className={c.actions}>
              <Button
                variant="default"
                disabled={busy !== ""}
                onClick={() => void runSuggest()}
              >
                {busy === "suggest" ? "Asking the model…" : "Suggest placeholders"}
              </Button>
              <Button
                variant="primary"
                disabled={busy !== "" || !dirty}
                onClick={() => void savePlan()}
              >
                {busy === "save" ? "Saving…" : "Save plan"}
              </Button>
              <Button
                variant="default"
                disabled={busy !== ""}
                onClick={() => void runPreview()}
              >
                {busy === "preview" ? "Rendering…" : "Preview with sample data"}
              </Button>
              {dirty && <span className={s.muted}>Unsaved changes</span>}
            </div>

            <p className={c.caption}>
              Suggesting asks the model to read this document and propose where
              things belong. It takes a few seconds and costs tokens. Nothing it
              proposes enters the plan until you accept it.
            </p>

            {dirty && (
              <div className={c.stack}>
                <Banner tone="warn" title="Preview shows the saved plan">
                  <p style={{ margin: 0 }}>
                    The preview is rendered by the server from the plan it has
                    stored, so anything changed since the last save is not in
                    it. Save first to see the current marks.
                  </p>
                </Banner>
              </div>
            )}

            {saved && (
              <div className={c.stack}>
                <Banner tone="note" title="Plan saved">
                  <p style={{ margin: 0 }}>{saved}</p>
                </Banner>
              </div>
            )}

            {problems.length > 0 && (
              <div className={c.stack}>
                <Banner tone="blocked" title="This plan does not match the document">
                  <ul className={c.problems}>
                    {problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </Banner>
              </div>
            )}

            {error && (
              <div className={c.stack}>
                <Banner tone="blocked" title="That did not work" serverMessage={error} />
              </div>
            )}

            {preview && !preview.opened && (
              <div className={c.stack}>
                <Banner tone="note" title="The preview did not open by itself">
                  <p style={{ margin: 0 }}>
                    {"A pop-up blocker refused it, because the file arrived after " +
                      "the click. "}
                    <a href={preview.url} target="_blank" rel="noreferrer">
                      Open the preview
                    </a>
                  </p>
                </Banner>
              </div>
            )}

            {stranded.length > 0 && (
              <div className={c.stack}>
                <Banner tone="warn" title="These point at blocks this document does not have">
                  <p style={{ margin: 0 }}>
                    The document was probably re-uploaded and its outline is a
                    different shape. Saving will refuse each of these by name;
                    remove them and mark the places again.
                  </p>
                </Banner>
                {stranded.map((entry) => (
                  <SuggestionChip
                    key={entry.key}
                    entry={entry}
                    state="placed"
                    occurrences={entry.literal ? occurrences.get(entry.literal) : undefined}
                    canMoveUp={false}
                    canMoveDown={false}
                    onAccept={(next) => edit(acceptSuggestion(plan, next))}
                    onReject={drop}
                    onBrief={(key, brief) => edit(updateBrief(plan, key, brief))}
                    onMove={() => undefined}
                  />
                ))}
              </div>
            )}
          </Section>

          <Section
            title="Phrases that stand in for a field"
            eyebrow={`${doc.data.outline.tokens.length} detected`}
          >
            <TokenPanel
              tokens={doc.data.outline.tokens}
              blocks={blocks}
              plan={plan}
              suggestions={tokenSuggestions}
              onChange={edit}
            />
          </Section>

          <Section
            title="The document"
            eyebrow={`${blocks.length} blocks, exactly as uploaded`}
          >
            <p className={c.caption}>
              This is a reading of the file, not an editor for it. Structure and
              styling are changed in Word and uploaded again; what is marked
              here is only where the system writes.
            </p>
            <BlockFlow blocks={blocks} chipsFor={chipsFor} onAddAfter={addAfter} />
          </Section>

          <Section
            title="Images in this document"
            eyebrow={`${doc.data.outline.media.length} files`}
          >
            <TemplateImages
              docId={docId}
              media={doc.data.outline.media}
              ocr={doc.data.ocr}
            />
          </Section>
        </>
      )}

      {mapping && plan && (
        <TableBinding
          block={mapping}
          plan={plan}
          onSave={(next: TableMapping) => {
            edit(setTableMapping(plan, mapping, next));
            setMapping(null);
          }}
          onClear={() => {
            edit(clearTableMapping(plan, mapping.path));
            setMapping(null);
          }}
          onCancel={() => setMapping(null)}
        />
      )}

      {leaving && (
        <div className={c.stack}>
          <Banner tone="warn" title="Leave without saving?">
            <p style={{ margin: "0 0 var(--s2)" }}>
              This plan has changes that are not on the server. Nothing here
              saves by itself.
            </p>
            <div className={c.actions}>
              <Button variant="danger" onClick={() => navigate("/checklist")}>
                Leave and lose them
              </Button>
              <Button variant="quiet" onClick={() => setLeaving(false)}>
                Stay
              </Button>
            </div>
          </Banner>
        </div>
      )}
    </Shell>
  );
}
