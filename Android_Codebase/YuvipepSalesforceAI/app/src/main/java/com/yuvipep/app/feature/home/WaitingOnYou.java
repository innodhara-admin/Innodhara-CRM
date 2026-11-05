package com.yuvipep.app.feature.home;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.dto.WaitingOnMeDto;

import java.util.Map;

/**
 * Text and tap target for the "waiting on you" Home card, and the name in the
 * block answer (customer ask, 21 Sep 2026). Kept free of Android types so it
 * is unit-tested.
 */
public final class WaitingOnYou {

    public enum Target { PROJECT, LEAD, NONE }

    private WaitingOnYou() { }

    /** "Task — reason · client" (the client, else the project, when known). */
    @NonNull
    public static String body(@NonNull WaitingOnMeDto.Item item) {
        StringBuilder b = new StringBuilder(item.title == null ? "" : item.title);
        if (item.blockedReason != null && !item.blockedReason.trim().isEmpty()) {
            b.append(" — ").append(item.blockedReason.trim());
        }
        String where = item.school != null && !item.school.trim().isEmpty()
                ? item.school.trim() : item.projectName;
        if (where != null && !where.trim().isEmpty()) b.append(" · ").append(where.trim());
        return b.toString();
    }

    /**
     * Where the card goes. Not the task itself: the task screen only finds the
     * caller's own tasks, and this one belongs to the colleague who is waiting.
     */
    @NonNull
    public static Target target(@NonNull WaitingOnMeDto.Item item) {
        if (item.projectId != null) return Target.PROJECT;
        if (item.leadId != null) return Target.LEAD;
        return Target.NONE;
    }

    /** The colleague the server told, from the block answer; null if nobody. */
    @Nullable
    public static String blockedOnName(@Nullable Map<String, Object> response) {
        if (response == null) return null;
        Object on = response.get("blocked_on");
        if (!(on instanceof Map)) return null;
        Object name = ((Map<?, ?>) on).get("name");
        return name instanceof String && !((String) name).trim().isEmpty()
                ? ((String) name).trim() : null;
    }
}
