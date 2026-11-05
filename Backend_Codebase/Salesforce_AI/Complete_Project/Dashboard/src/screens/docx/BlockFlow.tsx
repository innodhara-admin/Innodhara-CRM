/**
 * The uploaded document, read-only, as a vertical flow — Task 20 Step 2.
 *
 * This is the one screen in the console whose subject is a document rather than
 * a set of rows, so it is set like one: the organisation's own words in the
 * serif, the positional path in a mono gutter beside them, and the console's
 * proposals set into the flow where they would appear. The administrator is
 * deciding where text will land in *their* document, and a list of block ids
 * would not let them.
 *
 * Nothing here writes. The document is immutable — that is what makes a
 * positional path safe to store — so this component takes callbacks and renders
 * whatever chips the editor gives it.
 *
 * **No virtualisation.** Measured over the four real documents the outline is
 * 105, 119, 188 and 222 blocks, which render without it; a windowed list would
 * break find-in-page, which is how an administrator actually locates the
 * paragraph they are looking for.
 */
import { Fragment, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { endpoints } from "../../api/endpoints";
import type { Block } from "../../api/reads";
import { asApiError } from "../../ui/ItemScreen";
import { styles as s } from "../../ui/primitives";
import { fetchBinary } from "./binary";
import c from "./docx.module.css";

/** Six lines is the clamp; below this a paragraph is never clamped at all. */
const CLAMP_CHARS = 400;

const HEADING_CLASS: Record<number, string> = { 1: c.level1, 2: c.level2, 3: c.level3 };

function HeadingBlock({ block }: { block: Block }) {
  const level = block.level ?? 1;
  return (
    <>
      <p className={c.levelTag}>{`Heading ${level}`}</p>
      <h3 className={`${c.headingText} ${HEADING_CLASS[level] ?? c.level3}`}>
        {block.text}
      </h3>
    </>
  );
}

function ParagraphBlock({ block }: { block: Block }) {
  const [open, setOpen] = useState(false);
  const long = block.text.length > CLAMP_CHARS;
  return (
    <>
      <p className={`${c.docText} ${long && !open ? c.clamped : ""}`.trim()}>
        {block.text}
      </p>
      {long && (
        <button type="button" className={c.moreToggle} onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </>
  );
}

function TableBlock({ block }: { block: Block }) {
  const table = block.table;
  if (!table) return null;
  const [header, ...rest] = table.sample;
  return (
    <>
      <div className={c.tableScroll}>
        <table className={c.docTable}>
          <thead>
            <tr>
              {(header ?? []).map((cell, i) => (
                <th key={i} scope="col">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rest.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={c.caption}>
        {`${table.rows} rows, ${table.cols} columns · showing the first ` +
          `${table.sample.length} as they are in the document`}
      </p>
    </>
  );
}

/**
 * One image out of the stored document, fetched with the session token and
 * shown only once it is near the viewport.
 *
 * Lazy is not a nicety here: `School_YuviPep 360_2 1.docx` carries 33 images
 * and the largest is several megabytes, so loading them all on mount would send
 * tens of megabytes down a school's connection to draw thumbnails nobody has
 * scrolled to. `loading="lazy"` cannot do it — the bytes arrive through fetch,
 * not through the tag — so the observer does the same job one level up.
 */
export function TemplateImage({
  docId,
  name,
  ocrText,
}: {
  docId: string;
  name: string;
  ocrText?: string;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const el = holder.current;
    let cancelled = false;
    let objectUrl: string | null = null;

    async function load() {
      try {
        const blob = await fetchBinary(endpoints.templateDocMedia(docId, name));
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      } catch (err) {
        if (!cancelled) setFailed(asApiError(err)?.detail ?? String(err));
      }
    }

    // No observer in a non-browser environment; load rather than show nothing.
    if (!el || typeof IntersectionObserver === "undefined") {
      void load();
      return () => {
        cancelled = true;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        observer.disconnect();
        void load();
      },
      { rootMargin: "300px" },
    );
    observer.observe(el);
    return () => {
      cancelled = true;
      observer.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId, name]);

  return (
    <div ref={holder}>
      {src ? (
        <img className={c.image} src={src} alt={`${name}, from the template`} />
      ) : (
        <span className={c.imagePending} aria-hidden="true" />
      )}
      <p className={c.caption}>{name}</p>
      {failed && <p className={c.caption}>{`This image could not be read: ${failed}`}</p>}
      {ocrText && <p className={c.ocrText}>{`Text read from this image: ${ocrText}`}</p>}
    </div>
  );
}

/**
 * The images the document contains, together, with the text tesseract read out
 * of each.
 *
 * They are shown here rather than inline at their own blocks, and that is a
 * limitation with a cause worth recording. An image block's `images` field
 * carries **relationship ids** (`rId12`), because that is what
 * `outline.py::_image_ids` reads off the `a:blip`. The media route serves
 * **file names** (`image12.png`) and refuses anything not in `outline.media`.
 * Measured on the real documents: the two sets do not intersect at all — 0 of
 * 12 ids on `Essential Lab.docx`, 0 of 27 on `School_YuviPep 360_2 1.docx`. No
 * mapping between them exists anywhere in the stored outline, so an inline
 * thumbnail cannot be addressed without re-analysing every uploaded document.
 * The images, their names, and their OCR text are all still here; only their
 * position in the flow is not.
 */
export function TemplateImages({
  docId,
  media,
  ocr,
}: {
  docId: string;
  media: readonly string[];
  ocr: Record<string, string>;
}) {
  if (media.length === 0) {
    return <p className={s.muted}>This document has no images.</p>;
  }
  return (
    <div>
      {media.map((name) => (
        <TemplateImage key={name} docId={docId} name={name} ocrText={ocr[name] || undefined} />
      ))}
    </div>
  );
}

export function BlockFlow({
  blocks,
  chipsFor,
  onAddAfter,
}: {
  blocks: readonly Block[];
  /** Whatever the editor wants shown at this block — its chips. */
  chipsFor: (block: Block) => ReactNode;
  onAddAfter: (path: string) => void;
}) {
  return (
    <div className={c.flow}>
      {blocks.map((block) => (
        <Fragment key={block.path}>
          <div className={c.block}>
            <span className={c.path}>{block.path}</span>
            <div className={c.body}>
              {block.kind === "heading" && <HeadingBlock block={block} />}
              {block.kind === "paragraph" && <ParagraphBlock block={block} />}
              {block.kind === "table" && <TableBlock block={block} />}
              {block.kind === "image" && (
                <p className={c.caption}>
                  {`An image sits here (${block.images.join(", ")}). ` +
                    "The document's images are shown together below."}
                </p>
              )}
              {block.kind === "empty" && <div className={c.spacer} aria-hidden="true" />}
              {chipsFor(block)}
            </div>
          </div>
          <div className={c.insertRow}>
            {/* The path is already in the gutter beside this row; repeating it
                in 222 button labels would shout. It stays in the accessible
                name, where it is the only thing distinguishing one button from
                the next. */}
            <button
              type="button"
              className={c.insertButton}
              aria-label={`Add a placeholder after ${block.path}`}
              onClick={() => onAddAfter(block.path)}
            >
              + Add a placeholder here
            </button>
          </div>
        </Fragment>
      ))}
    </div>
  );
}
