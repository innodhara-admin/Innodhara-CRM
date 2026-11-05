package com.yuvipep.app.feature.notifications;

import android.Manifest;
import android.app.Notification;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.db.CachedNotification;
import com.yuvipep.app.core.net.TokenStore;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import dagger.hilt.EntryPoint;
import dagger.hilt.InstallIn;
import dagger.hilt.android.EntryPointAccessors;
import dagger.hilt.components.SingletonComponent;

/**
 * The 15-minute background poll (07 §2, until FCM in Phase 8): fetch the
 * delta, then raise local system notifications for unseen unread items,
 * grouped per kind and deep-linked into the notification center.
 */
public class NotificationPollWorker extends Worker {

    public static final String WORK_NAME = "notifications-poll";
    private static final String PREFS = "yuvipep_notify";
    private static final String KEY_LAST_STAMP = "last_notified_created_at";

    @EntryPoint
    @InstallIn(SingletonComponent.class)
    public interface Deps {
        NotificationRepository notificationRepository();

        TokenStore tokenStore();
    }

    public NotificationPollWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        Deps deps = EntryPointAccessors.fromApplication(getApplicationContext(), Deps.class);
        if (!deps.tokenStore().hasSession()) {
            return Result.success();    // signed out — nothing to poll
        }
        deps.notificationRepository().refreshBlocking();

        Context context = getApplicationContext();
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(
                Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            return Result.success();    // user hasn't allowed notifications
        }

        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String lastStamp = prefs.getString(KEY_LAST_STAMP, "");
        List<CachedNotification> unread = deps.notificationRepository().unreadCached();

        // Only items newer than what we already alerted about.
        Map<String, List<CachedNotification>> byChannel = new LinkedHashMap<>();
        String newestStamp = lastStamp;
        for (CachedNotification n : unread) {
            if (n.createdAt == null || n.createdAt.compareTo(lastStamp) <= 0) continue;
            String channel = NotificationChannels.forKind(n.kind);
            byChannel.computeIfAbsent(channel, k -> new ArrayList<>()).add(n);
            if (n.createdAt.compareTo(newestStamp) > 0) {
                newestStamp = n.createdAt;
            }
        }
        if (byChannel.isEmpty()) {
            return Result.success();
        }

        NotificationManagerCompat manager = NotificationManagerCompat.from(context);
        int idBase = 100;
        for (Map.Entry<String, List<CachedNotification>> entry : byChannel.entrySet()) {
            manager.notify(idBase++, buildGrouped(context, entry.getKey(), entry.getValue()));
        }
        prefs.edit().putString(KEY_LAST_STAMP, newestStamp).apply();
        return Result.success();
    }

    private Notification buildGrouped(Context context, String channelId,
                                      List<CachedNotification> items) {
        Intent open = new Intent(context, MainActivity.class)
                .putExtra(MainActivity.EXTRA_OPEN_NOTIFICATIONS, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent tap = PendingIntent.getActivity(context, channelId.hashCode(), open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.InboxStyle style = new NotificationCompat.InboxStyle();
        for (int i = 0; i < Math.min(items.size(), 5); i++) {
            style.addLine(items.get(i).title);
        }
        String label = NotificationChannels.labelFor(channelId);
        return new NotificationCompat.Builder(context, channelId)
                .setSmallIcon(R.drawable.ic_stat_bell)
                .setContentTitle(label)
                .setContentText(items.size() == 1 ? items.get(0).title
                        : items.size() + " new")
                .setStyle(style)
                .setNumber(items.size())
                .setAutoCancel(true)
                .setContentIntent(tap)
                .build();
    }
}
