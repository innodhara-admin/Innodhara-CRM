package com.yuvipep.app.feature.notifications;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;

import com.yuvipep.app.R;
import com.yuvipep.app.core.db.CachedNotification;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.ItemNotificationBinding;

import java.util.Objects;

/** Notification feed rows; unread shows the dot, tap deep-links. */
public class NotificationAdapter
        extends ListAdapter<CachedNotification, NotificationAdapter.Holder> {

    public interface Listener {
        void onTap(@NonNull CachedNotification notification);
    }

    private final Listener listener;

    public NotificationAdapter(@NonNull Listener listener) {
        super(DIFF);
        this.listener = listener;
    }

    private static final DiffUtil.ItemCallback<CachedNotification> DIFF =
            new DiffUtil.ItemCallback<CachedNotification>() {
                @Override
                public boolean areItemsTheSame(@NonNull CachedNotification a,
                                               @NonNull CachedNotification b) {
                    return a.id.equals(b.id);
                }

                @Override
                public boolean areContentsTheSame(@NonNull CachedNotification a,
                                                  @NonNull CachedNotification b) {
                    return a.isRead == b.isRead
                            && Objects.equals(a.title, b.title)
                            && Objects.equals(a.body, b.body);
                }
            };

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemNotificationBinding.inflate(
                LayoutInflater.from(parent.getContext()), parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        holder.bind(getItem(position));
    }

    class Holder extends RecyclerView.ViewHolder {
        private final ItemNotificationBinding binding;

        Holder(ItemNotificationBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(CachedNotification n) {
            binding.notifTitle.setText(n.title);
            binding.notifBody.setText(n.body);
            binding.notifBody.setVisibility(
                    n.body == null || n.body.isEmpty() ? View.GONE : View.VISIBLE);
            binding.notifTime.setText(Times.ago(Times.parseUtc(n.createdAt)));
            binding.unreadDot.setVisibility(n.isRead ? View.INVISIBLE : View.VISIBLE);
            binding.kindIcon.setImageResource(iconFor(n.kind));
            binding.getRoot().setOnClickListener(v -> listener.onTap(n));
        }
    }

    private static int iconFor(String kind) {
        switch (NotificationChannels.forKind(kind)) {
            case NotificationChannels.APPROVALS:
                return R.drawable.ic_tab_approvals;
            case NotificationChannels.TASKS:
                return R.drawable.ic_tab_tasks;
            case NotificationChannels.ESCALATIONS:
                return R.drawable.ic_tab_alert;
            case NotificationChannels.REMINDERS:
                return R.drawable.ic_tab_inbox;
            default:
                return R.drawable.ic_bell;
        }
    }
}
