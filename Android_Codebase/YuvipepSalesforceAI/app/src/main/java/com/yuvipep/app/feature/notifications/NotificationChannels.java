package com.yuvipep.app.feature.notifications;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;

import androidx.annotation.NonNull;

/**
 * System notification channels mapped from backend `kind` (07 §3):
 * Approvals (high), Tasks, Escalations (high), Reminders, General (low).
 * Created once at app start; users control each in system settings.
 */
public final class NotificationChannels {

    public static final String APPROVALS = "approvals";
    public static final String TASKS = "tasks";
    public static final String ESCALATIONS = "escalations";
    public static final String REMINDERS = "reminders";
    public static final String GENERAL = "general";
    /** Phase 2: recorder foreground + upload progress/failures. */
    public static final String RECORDING = "recording";
    public static final String UPLOADS = "uploads";

    private NotificationChannels() {
    }

    public static void createAll(@NonNull Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;
        manager.createNotificationChannel(channel(APPROVALS, "Approvals",
                NotificationManager.IMPORTANCE_HIGH));
        manager.createNotificationChannel(channel(TASKS, "Tasks",
                NotificationManager.IMPORTANCE_DEFAULT));
        manager.createNotificationChannel(channel(ESCALATIONS, "Escalations",
                NotificationManager.IMPORTANCE_HIGH));
        manager.createNotificationChannel(channel(REMINDERS, "Reminders",
                NotificationManager.IMPORTANCE_DEFAULT));
        manager.createNotificationChannel(channel(GENERAL, "General",
                NotificationManager.IMPORTANCE_LOW));
        manager.createNotificationChannel(channel(RECORDING, "Meeting recording",
                NotificationManager.IMPORTANCE_LOW));
        manager.createNotificationChannel(channel(UPLOADS, "Uploads",
                NotificationManager.IMPORTANCE_DEFAULT));
    }

    private static NotificationChannel channel(String id, String name, int importance) {
        return new NotificationChannel(id, name, importance);
    }

    /** Backend notification `kind` → channel id. Unknown kinds stay general. */
    @NonNull
    public static String forKind(String kind) {
        if (kind == null) return GENERAL;
        switch (kind) {
            case "approval_waiting":
                return APPROVALS;
            case "task_assigned":
            case "meeting_processed":
            case "plan_updated":
                return TASKS;
            case "escalation":
                return ESCALATIONS;
            case "reminder":
                return REMINDERS;
            default:
                return GENERAL;
        }
    }

    /** Human group label per channel for the grouped system notifications. */
    @NonNull
    public static String labelFor(@NonNull String channelId) {
        switch (channelId) {
            case APPROVALS: return "Approvals waiting";
            case TASKS: return "Task updates";
            case ESCALATIONS: return "Escalations";
            case REMINDERS: return "Reminders";
            default: return "Updates";
        }
    }
}
