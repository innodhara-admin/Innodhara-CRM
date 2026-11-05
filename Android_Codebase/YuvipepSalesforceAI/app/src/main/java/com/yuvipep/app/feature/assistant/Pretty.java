package com.yuvipep.app.feature.assistant;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.feature.leads.LeadStates;

import java.util.List;
import java.util.Map;

/**
 * Generic renderer for whatever shape an agent tool returned — maps become
 * "Label: value" lines, lists are joined, ids and empties are dropped. No
 * schema is assumed, so a brand-new backend tool renders day one.
 */
public final class Pretty {

    private Pretty() {
    }

    private static final int MAX_LINES = 18;

    /** Render any JSON-ish value into short human lines. */
    @NonNull
    public static String value(@Nullable Object value) {
        String out = render(unwrap(value), 0).trim();
        String[] lines = out.split("\n");
        if (lines.length <= MAX_LINES) return out;
        StringBuilder capped = new StringBuilder();
        for (int i = 0; i < MAX_LINES; i++) capped.append(lines[i]).append('\n');
        return capped.append('…').toString();
    }

    /**
     * Big tool results arrive as truncated STRING previews from the backend
     * (base.py `_preview`, 800 chars + "…"). Raw JSON on a card is noise —
     * parse it back to structure when possible; when the truncation broke
     * the JSON, drop the body (the card title + the reply carry the meaning).
     */
    @Nullable
    private static Object unwrap(@Nullable Object value) {
        if (!(value instanceof String)) return value;
        String text = ((String) value).trim();
        if (text.endsWith("…")) text = text.substring(0, text.length() - 1);
        boolean looksJson = text.startsWith("{") || text.startsWith("[")
                || text.startsWith("\"");
        if (!looksJson) return value;
        try {
            return new com.google.gson.Gson().fromJson(text, Object.class);
        } catch (RuntimeException e) {
            return null; // truncated/broken JSON — omit rather than dump
        }
    }

    private static String render(@Nullable Object value, int depth) {
        if (value == null) return "";
        if (value instanceof Map) {
            StringBuilder out = new StringBuilder();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                String key = String.valueOf(entry.getKey());
                if (skipKey(key)) continue;
                String rendered = render(entry.getValue(), depth + 1).trim();
                if (rendered.isEmpty() || "false".equals(rendered)) {
                    // "Important: false" is not news; saying nothing is.
                    continue;
                }
                String label = LeadStates.label(key);
                if ("true".equals(rendered)) {
                    out.append(indent(depth)).append(label).append('\n');
                } else if (rendered.contains("\n")) {
                    // Anything with several lines of its own (the contacts,
                    // a list of notes) reads as a block under its heading —
                    // glued onto "Contacts: " it ran together into a wall.
                    out.append(indent(depth)).append(label).append(":\n");
                    for (String line : rendered.split("\n")) {
                        out.append(indent(depth)).append("  ").append(line.trim()).append('\n');
                    }
                } else {
                    out.append(indent(depth)).append(label)
                            .append(": ").append(rendered).append('\n');
                }
            }
            return out.toString();
        }
        if (value instanceof List) {
            StringBuilder out = new StringBuilder();
            for (Object element : (List<?>) value) {
                String rendered = render(element, depth).trim();
                if (rendered.isEmpty()) continue;
                if (out.length() > 0) out.append('\n');
                String[] lines = rendered.split("\n");
                if (lines.length > 1) {
                    // One bullet per entry, so two contacts are two people
                    // rather than four anonymous lines.
                    out.append("• ").append(lines[0].trim());
                    for (int i = 1; i < lines.length; i++) {
                        out.append('\n').append("  ").append(lines[i].trim());
                    }
                } else {
                    out.append(rendered);
                }
            }
            return out.toString();
        }
        if (value instanceof Double && ((Double) value) == Math.floor((Double) value)
                && !((Double) value).isInfinite()) {
            return String.valueOf(((Double) value).longValue());
        }
        String text = String.valueOf(value);
        if (text.isEmpty() || "[]".equals(text) || "{}".equals(text)
                || "null".equals(text)) {
            return "";
        }
        return text;
    }

    /** Raw ids mean nothing on a card; the card's tap already routes there. */
    private static boolean skipKey(@NonNull String key) {
        return key.equals("id") || key.endsWith("_id") || key.equals("org_id");
    }

    private static String indent(int depth) {
        StringBuilder out = new StringBuilder();
        for (int i = 1; i < depth; i++) out.append("  ");
        return out.toString();
    }
}
