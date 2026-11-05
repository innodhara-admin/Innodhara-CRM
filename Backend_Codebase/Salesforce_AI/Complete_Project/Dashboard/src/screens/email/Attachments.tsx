/**
 * The default files one email template sends (28 Oct 2026). Added and removed
 * here, one at a time; a new version of the Word file keeps them.
 */
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import type { EmailTemplate } from "../../api/reads";
import { asApiError } from "../../ui/ItemScreen";
import { Button, styles as s } from "../../ui/primitives";
import { ATTACHMENT_ACCEPT, MAX_ATTACHMENT_BYTES } from "./email";

export function Attachments({ template }: { template: EmailTemplate }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      await queryClient.invalidateQueries({ queryKey: ["emailTemplates"] });
    } catch (err) {
      setError(asApiError(err)?.detail ?? String(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  function add(file: File) {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setError(`One attachment can be at most ${MAX_ATTACHMENT_BYTES / (1024 * 1024)} MB.`);
      return;
    }
    const form = new FormData();
    form.append("file", file);
    void run(() =>
      request(endpoints.emailTemplateAttachments(template.id), {
        as: "org",
        method: "POST",
        body: form,
      }),
    );
  }

  return (
    <div>
      {template.attachments.length === 0 && <span className={s.muted}>no files</span>}
      {template.attachments.map((a) => (
        <div key={a.id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center" }}>
          <span className={s.mono}>{a.filename}</span>
          <Button
            variant="quiet"
            disabled={busy}
            onClick={() =>
              run(() =>
                request(endpoints.emailTemplateAttachment(template.id, a.id), {
                  as: "org",
                  method: "DELETE",
                }),
              )
            }
          >
            Remove
          </Button>
        </div>
      ))}
      {template.is_current && (
        <input
          ref={input}
          type="file"
          accept={ATTACHMENT_ACCEPT}
          disabled={busy}
          aria-label={`Add a file to ${template.name}`}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) add(file);
          }}
        />
      )}
      {error && (
        <p style={{ color: "var(--status-blocked)", fontSize: "var(--text-xs)", margin: 0 }}>
          {error}
        </p>
      )}
    </div>
  );
}
