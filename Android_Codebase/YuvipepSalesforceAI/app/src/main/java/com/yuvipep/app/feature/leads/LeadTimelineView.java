package com.yuvipep.app.feature.leads;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.util.AttributeSet;
import android.util.TypedValue;
import android.view.View;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.util.Times;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The journey strip under the lead header: where this lead has been, where it
 * is, and what comes next.
 *
 * <pre>
 *   ●━━━━━━━━●━━━━━━━━◉ ─ ─ ─ ─ ○
 *   Assigned  Cold      Open      Active
 *   to Priya  calling   2h ago
 *   by Siva   3d        "Good response"
 * </pre>
 *
 * Drawn rather than composed from child views: the nodes are a dot, a line
 * and three short labels each, and a custom {@code onDraw} keeps that one
 * file instead of a layout, an adapter and a row binder. Its parent is a
 * {@link android.widget.HorizontalScrollView}, so this measures its full
 * natural width and lets the parent scroll it.
 *
 * Fed from {@code state_history}, which the backend returns newest-first;
 * {@link #bind} reverses it so the strip reads left to right in time order.
 */
public class LeadTimelineView extends View {

    /** One dot on the strip. */
    private static final class Node {
        String title;           // "Cold calling"
        @Nullable String when;  // "3d", "2h ago"
        @Nullable String note;  // the reason the mover logged
        int color;
        boolean isCurrent;      // hollow ring
        boolean isFuture;       // dashed, greyed
    }

    private static final int NODE_GAP_DP = 96;
    private static final int DOT_RADIUS_DP = 7;
    private static final int PAD_DP = 20;

    private final Paint linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dotPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint titlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint metaPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private final List<Node> nodes = new ArrayList<>();
    private float density;

    public LeadTimelineView(Context context) {
        this(context, null);
    }

    public LeadTimelineView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        density = getResources().getDisplayMetrics().density;
        titlePaint.setTextSize(sp(12));
        titlePaint.setTypeface(Typeface.DEFAULT_BOLD);
        metaPaint.setTextSize(sp(10));
        linePaint.setStrokeWidth(dp(2));
        linePaint.setStyle(Paint.Style.STROKE);
    }

    private float dp(float value) {
        return value * density;
    }

    private float sp(float value) {
        return TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, value,
                getResources().getDisplayMetrics());
    }

    /**
     * Rebuild the strip from a lead's history.
     *
     * @param history newest-first, as the API returns it. May be null or empty,
     *                in which case the strip hides itself rather than drawing
     *                an empty rail.
     */
    public void bind(@Nullable List<LeadDetailResponse.HistoryRow> history,
                     @Nullable String currentState) {
        nodes.clear();
        if (history == null || history.isEmpty()) {
            setVisibility(GONE);
            return;
        }
        List<LeadDetailResponse.HistoryRow> ordered = new ArrayList<>(history);
        Collections.reverse(ordered);          // oldest first — the reading order

        for (int i = 0; i < ordered.size(); i++) {
            LeadDetailResponse.HistoryRow row = ordered.get(i);
            Node node = new Node();
            node.title = LeadStates.label(row.to);
            node.when = row.at == null ? null : Times.ago(Times.parseUtc(row.at));
            node.note = row.reason;
            node.color = ContextCompat.getColor(getContext(), LeadStates.color(row.to));
            // The last row is only "current" if the lead really is still there;
            // a state changed by something other than a history write would
            // otherwise light up the wrong dot.
            node.isCurrent = i == ordered.size() - 1
                    && (currentState == null || currentState.equals(row.to));
            nodes.add(node);
        }

        String next = nextState(currentState);
        if (next != null) {
            Node ghost = new Node();
            ghost.title = LeadStates.label(next);
            ghost.isFuture = true;
            ghost.color = ContextCompat.getColor(getContext(),
                    R.color.md_light_outline);
            nodes.add(ghost);
        }
        setVisibility(VISIBLE);
        requestLayout();
        invalidate();
    }

    /**
     * The one state worth drawing ahead of the lead — the expected happy path,
     * not every legal move. Terminal states get no ghost.
     */
    @Nullable
    private static String nextState(@Nullable String state) {
        if (state == null) return null;
        switch (state) {
            case "cold_calling": return "open";
            case "open": return "active";
            case "active": return "execution_in_progress";
            case "execution_in_progress": return "client_execution_in_progress";
            case "client_execution_in_progress": return "closed";
            default: return null;   // closed, lost_for_now, cold
        }
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = (int) (dp(PAD_DP) * 2 + Math.max(nodes.size(), 1) * dp(NODE_GAP_DP));
        int height = (int) dp(74);
        setMeasuredDimension(
                resolveSize(width, widthMeasureSpec),
                resolveSize(height, heightMeasureSpec));
    }

    @Override
    protected void onDraw(@NonNull Canvas canvas) {
        if (nodes.isEmpty()) return;

        float gap = dp(NODE_GAP_DP);
        float radius = dp(DOT_RADIUS_DP);
        float cy = dp(14);
        float startX = dp(PAD_DP);

        for (int i = 0; i < nodes.size(); i++) {
            Node node = nodes.get(i);
            float cx = startX + i * gap;

            // The rail into this node, coloured by the node it arrives at.
            if (i > 0) {
                Node previous = nodes.get(i - 1);
                linePaint.setColor(node.isFuture ? node.color : previous.color);
                linePaint.setAlpha(node.isFuture ? 110 : 255);
                linePaint.setPathEffect(node.isFuture
                        ? new android.graphics.DashPathEffect(
                                new float[]{dp(4), dp(4)}, 0)
                        : null);
                canvas.drawLine(cx - gap + radius + dp(3), cy,
                        cx - radius - dp(3), cy, linePaint);
            }

            dotPaint.setColor(node.color);
            if (node.isCurrent || node.isFuture) {
                // A ring: where the lead is now, and where it is headed.
                dotPaint.setStyle(Paint.Style.STROKE);
                dotPaint.setStrokeWidth(dp(2.5f));
                dotPaint.setAlpha(node.isFuture ? 130 : 255);
                canvas.drawCircle(cx, cy, radius - dp(1), dotPaint);
            } else {
                dotPaint.setStyle(Paint.Style.FILL);
                dotPaint.setAlpha(255);
                canvas.drawCircle(cx, cy, radius, dotPaint);
            }

            // Labels hang under their own dot, left-aligned to it, and are
            // clipped to the gap so neighbours never collide.
            float textX = cx - radius;
            float available = gap - dp(12);

            titlePaint.setColor(node.color);
            titlePaint.setAlpha(node.isFuture ? 130 : 255);
            canvas.drawText(ellipsise(node.title, titlePaint, available),
                    textX, cy + dp(22), titlePaint);

            metaPaint.setColor(node.color);
            metaPaint.setAlpha(node.isFuture ? 110 : 180);
            float metaY = cy + dp(36);
            if (node.when != null) {
                canvas.drawText(ellipsise(node.when, metaPaint, available),
                        textX, metaY, metaPaint);
                metaY += dp(13);
            }
            if (node.note != null && !node.note.isEmpty()) {
                canvas.drawText(ellipsise(node.note, metaPaint, available),
                        textX, metaY, metaPaint);
            }
        }
    }

    private static String ellipsise(@Nullable String text, Paint paint, float maxWidth) {
        if (text == null) return "";
        if (paint.measureText(text) <= maxWidth) return text;
        String suffix = "…";
        int end = text.length();
        while (end > 1 && paint.measureText(text.substring(0, end) + suffix) > maxWidth) {
            end--;
        }
        return text.substring(0, end) + suffix;
    }
}
