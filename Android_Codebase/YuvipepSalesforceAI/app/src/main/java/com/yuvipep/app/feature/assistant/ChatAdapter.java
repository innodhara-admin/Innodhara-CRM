package com.yuvipep.app.feature.assistant;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.yuvipep.app.R;
import com.yuvipep.app.databinding.ItemChatActionBinding;
import com.yuvipep.app.databinding.ItemChatApprovalBinding;
import com.yuvipep.app.databinding.ItemChatQuestionBinding;
import com.yuvipep.app.databinding.ItemChatReplyBinding;
import com.yuvipep.app.databinding.ItemChatUserBinding;

import java.util.List;

import io.noties.markwon.Markwon;

/**
 * The transcript: user bubbles, reply bubbles, action cards (tap to open,
 * Why chip), and inline approval cards (04 §2 — approve without leaving the
 * conversation).
 */
public class ChatAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {

    public interface Listener {
        void onOpenEntity(@NonNull String entityType, @NonNull String entityId);

        void onWhy(@NonNull String entityType, @NonNull String entityId);

        void onApprove(@NonNull ChatItem item);

        void onReject(@NonNull ChatItem item);

        /** The user tapped one of the answers the assistant asked about. */
        void onAnswer(@NonNull String candidate);

        /**
         * A tap on a chip that is a complete answer by itself (a client
         * draft's "Create it", "Me", a colleague's name) — send it now.
         */
        default void onAnswerNow(@NonNull String candidate) {
            onAnswer(candidate);
        }
    }

    private static final int TYPE_USER = 0;
    private static final int TYPE_REPLY = 1;
    private static final int TYPE_ACTION = 2;
    private static final int TYPE_APPROVAL = 3;
    private static final int TYPE_QUESTION = 4;

    private final List<ChatItem> items;
    private final Listener listener;
    private final Markwon markwon;

    public ChatAdapter(@NonNull List<ChatItem> items, @NonNull Listener listener,
                       @NonNull Markwon markwon) {
        this.items = items;
        this.listener = listener;
        this.markwon = markwon;
    }

    @Override
    public int getItemViewType(int position) {
        switch (items.get(position).kind) {
            case USER: return TYPE_USER;
            case REPLY: return TYPE_REPLY;
            case ACTION: return TYPE_ACTION;
            case QUESTION: return TYPE_QUESTION;
            default: return TYPE_APPROVAL;
        }
    }

    @NonNull
    @Override
    public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent,
                                                      int viewType) {
        LayoutInflater inflater = LayoutInflater.from(parent.getContext());
        switch (viewType) {
            case TYPE_USER:
                return new UserHolder(ItemChatUserBinding.inflate(inflater, parent, false));
            case TYPE_REPLY:
                return new ReplyHolder(ItemChatReplyBinding.inflate(inflater, parent, false));
            case TYPE_ACTION:
                return new ActionHolder(ItemChatActionBinding.inflate(inflater, parent, false));
            case TYPE_QUESTION:
                return new QuestionHolder(
                        ItemChatQuestionBinding.inflate(inflater, parent, false));
            default:
                return new ApprovalHolder(ItemChatApprovalBinding.inflate(inflater, parent, false));
        }
    }

    @Override
    public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
        ChatItem item = items.get(position);
        if (holder instanceof UserHolder) {
            ((UserHolder) holder).bind(item);
        } else if (holder instanceof ReplyHolder) {
            ((ReplyHolder) holder).bind(item, markwon);
        } else if (holder instanceof ActionHolder) {
            ((ActionHolder) holder).bind(item, listener);
        } else if (holder instanceof QuestionHolder) {
            ((QuestionHolder) holder).bind(item, listener, markwon);
        } else {
            ((ApprovalHolder) holder).bind(item, listener, this);
        }
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static class UserHolder extends RecyclerView.ViewHolder {
        private final ItemChatUserBinding row;

        UserHolder(ItemChatUserBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(ChatItem item) {
            row.userText.setText(item.text);
            bindOptional(row.userMeta, item.meta);
        }
    }

    static class ReplyHolder extends RecyclerView.ViewHolder {
        private final ItemChatReplyBinding row;

        ReplyHolder(ItemChatReplyBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(ChatItem item, Markwon markwon) {
            markwon.setMarkdown(row.replyText, item.text != null ? item.text : "");
            bindOptional(row.replyMeta, item.meta);
        }
    }

    static class ActionHolder extends RecyclerView.ViewHolder {
        private final ItemChatActionBinding row;

        ActionHolder(ItemChatActionBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(ChatItem item, Listener listener) {
            row.actionTitle.setText(item.title);
            bindOptional(row.actionBody, item.body);
            row.actionFailedBadge.setVisibility(item.ok ? View.GONE : View.VISIBLE);
            boolean canOpen = item.entityType != null && item.entityId != null;
            row.whyChip.setVisibility(canOpen ? View.VISIBLE : View.GONE);
            row.openChip.setVisibility(canOpen ? View.VISIBLE : View.GONE);
            if (canOpen) {
                row.whyChip.setOnClickListener(v ->
                        listener.onWhy(item.entityType, item.entityId));
                row.openChip.setOnClickListener(v ->
                        listener.onOpenEntity(item.entityType, item.entityId));
                row.getRoot().setOnClickListener(v ->
                        listener.onOpenEntity(item.entityType, item.entityId));
            } else {
                row.getRoot().setOnClickListener(null);
            }
            row.getRoot().setClickable(canOpen);
        }
    }

    /**
     * The assistant is unsure and is asking (F28). This card exists so a
     * sensible clarifying question stops looking like a crash: the same
     * response used to render as a red "failed" badge, which taught people
     * that asking them something was a malfunction.
     */
    static class QuestionHolder extends RecyclerView.ViewHolder {
        private final ItemChatQuestionBinding row;

        QuestionHolder(ItemChatQuestionBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(ChatItem item, Listener listener, Markwon markwon) {
            markwon.setMarkdown(row.questionBody, item.body != null ? item.body : "");
            bindDraft(item);
            row.questionChips.removeAllViews();
            if (item.candidates == null || item.candidates.isEmpty()) {
                row.questionChips.setVisibility(View.GONE);
                return;
            }
            row.questionChips.setVisibility(View.VISIBLE);
            for (String candidate : item.candidates) {
                com.google.android.material.chip.Chip chip =
                        new com.google.android.material.chip.Chip(
                                row.getRoot().getContext());
                chip.setText(candidate);
                chip.setEnsureMinTouchTargetSize(false);
                // Fills the box rather than answering for them: the user still
                // reads it and taps send, the same rule the Inbox reply route
                // follows — nothing is said on their behalf. A client draft's
                // chips are the exception: each is the whole answer, the
                // person picked it, and nothing is created before the
                // read-back and an explicit "Create it".
                if (item.clientDraft) {
                    chip.setOnClickListener(v -> listener.onAnswerNow(candidate));
                } else {
                    chip.setOnClickListener(v -> listener.onAnswer(candidate));
                }
                row.questionChips.addView(chip);
            }
        }

        private void bindDraft(ChatItem item) {
            android.content.Context context = row.getRoot().getContext();
            row.questionNothingDone.setText(item.clientDraft
                    ? R.string.assistant_draft_nothing_created
                    : R.string.assistant_question_nothing_done);
            row.draftRows.removeAllViews();
            if (!item.clientDraft || item.draftRows == null || item.draftRows.isEmpty()) {
                row.draftBox.setVisibility(View.GONE);
                return;
            }
            row.draftBox.setVisibility(View.VISIBLE);
            bindOptional(row.draftStep, item.draftStep);
            int color = androidx.core.content.ContextCompat.getColor(context,
                    R.color.amber_on_container);
            for (String[] pair : item.draftRows) {
                android.widget.TextView line = new android.widget.TextView(context);
                android.text.SpannableStringBuilder text =
                        new android.text.SpannableStringBuilder();
                text.append(pair[0]).append("  ");
                text.setSpan(new android.text.style.StyleSpan(android.graphics.Typeface.BOLD),
                        0, pair[0].length(), android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                text.append(pair[1]);
                line.setText(text);
                // Appearance first: it would otherwise reset the colour.
                androidx.core.widget.TextViewCompat.setTextAppearance(line,
                        com.google.android.material.R.style.TextAppearance_Material3_BodyMedium);
                line.setTextColor(color);
                line.setPadding(0, 2, 0, 2);
                row.draftRows.addView(line);
            }
        }
    }

    static class ApprovalHolder extends RecyclerView.ViewHolder {
        private final ItemChatApprovalBinding row;

        ApprovalHolder(ItemChatApprovalBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(ChatItem item, Listener listener, ChatAdapter adapter) {
            row.approvalTitle.setText(item.title);
            bindOptional(row.approvalBody, item.body);

            boolean pending = "pending".equals(item.approvalState);
            row.approveButton.setVisibility(pending ? View.VISIBLE : View.GONE);
            row.rejectButton.setVisibility(pending ? View.VISIBLE : View.GONE);
            row.approveButton.setOnClickListener(v -> listener.onApprove(item));
            row.rejectButton.setOnClickListener(v -> listener.onReject(item));

            String status = null;
            if ("approved".equals(item.approvalState)) {
                status = row.getRoot().getContext().getString(R.string.assistant_sent);
            } else if ("rejected".equals(item.approvalState)) {
                status = row.getRoot().getContext().getString(R.string.assistant_rejected);
            } else if (item.approvalError != null) {
                status = item.approvalError;
            }
            bindOptional(row.approvalStatus, status);
        }
    }

    private static void bindOptional(@NonNull android.widget.TextView view,
                                     @androidx.annotation.Nullable String value) {
        if (value == null || value.isEmpty()) {
            view.setVisibility(View.GONE);
        } else {
            view.setText(value);
            view.setVisibility(View.VISIBLE);
        }
    }
}
