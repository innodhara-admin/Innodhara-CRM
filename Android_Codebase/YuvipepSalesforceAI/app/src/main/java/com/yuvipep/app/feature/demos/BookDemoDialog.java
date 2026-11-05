package com.yuvipep.app.feature.demos;

import android.app.TimePickerDialog;
import android.content.Context;
import android.text.format.DateFormat;
import android.util.TypedValue;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.DemoRequests;
import com.yuvipep.app.core.net.dto.DemoTeamDto;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;
import com.yuvipep.app.core.voice.VoiceEditText;
import com.yuvipep.app.feature.tasks.TasksRepository;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicReference;

/**
 * "Book demo" from a lead screen (03 §11): date + optional time, team
 * picker (any role may read the team list; the backend gates the booking
 * itself), optional notes. The result dialog renders the backend's own
 * clash warning and invite outcome verbatim — nothing invisible.
 */
public final class BookDemoDialog {

    private BookDemoDialog() {
    }

    public interface Host {
        void onBooked(@NonNull String resultMessage);

        void onFailed(@NonNull String backendMessage);
    }

    public static void open(@NonNull Context context, @NonNull DemosRepository repository,
                            @NonNull TasksRepository tasksRepository,
                            @NonNull String leadId, @Nullable String leadName,
                            @NonNull Host host) {
        repository.teams(result -> {
            List<DemoTeamDto> teams = result.isSuccess() && result.data != null
                    ? result.data : new ArrayList<>();
            show(context, repository, tasksRepository, leadId, leadName, teams, host);
        });
    }

    private static void show(@NonNull Context context, @NonNull DemosRepository repository,
                             @NonNull TasksRepository tasksRepository,
                             @NonNull String leadId, @Nullable String leadName,
                             @NonNull List<DemoTeamDto> teams, @NonNull Host host) {
        LinearLayout wrapper = new LinearLayout(context);
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * context.getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        // Tap-to-pick date and time (no more typing an ISO string by hand).
        // Holders carry the machine-formatted values the backend expects:
        // date as yyyy-MM-dd, time as HH:mm (24h, empty = optional).
        final String[] pickedDate = {null};
        final String[] pickedTime = {null};

        // Load this user's tasks in the background so the date calendar can dot
        // the days that have tasks due (and long-press can list them). If it
        // hasn't arrived by the time the field is tapped, the calendar simply
        // shows no dots — never blocks the booking.
        final AtomicReference<List<TaskDto>> tasksForDots = new AtomicReference<>(null);
        tasksRepository.myTasks(result -> {
            if (result.isSuccess() && result.data != null) {
                tasksForDots.set(result.data.tasks);
            }
        });

        TextView date = pickerField(context, context.getString(R.string.demos_pick_date_hint));
        wrapper.addView(date);
        date.setOnClickListener(v -> CalendarPickerDialog.show(
                context, pickedDate[0], tasksForDots.get(), iso -> {
                    pickedDate[0] = iso;
                    date.setText(iso);
                }));

        TextView time = pickerField(context, context.getString(R.string.demos_pick_time_hint));
        wrapper.addView(time);
        time.setOnClickListener(v -> {
            Calendar now = Calendar.getInstance();
            new TimePickerDialog(context, (view, hour, minute) -> {
                pickedTime[0] = String.format(Locale.US, "%02d:%02d", hour, minute);
                time.setText(pickedTime[0]);
            }, now.get(Calendar.HOUR_OF_DAY), now.get(Calendar.MINUTE),
                    DateFormat.is24HourFormat(context)).show();
        });

        List<String> teamLabels = new ArrayList<>();
        teamLabels.add(context.getString(R.string.demos_no_team));
        for (DemoTeamDto team : teams) teamLabels.add(team.name);
        Spinner teamPicker = new Spinner(context);
        teamPicker.setAdapter(new ArrayAdapter<>(context,
                android.R.layout.simple_spinner_dropdown_item, teamLabels));
        wrapper.addView(teamPicker);

        EditText notes = new VoiceEditText(context);
        notes.setHint(R.string.demos_notes_hint);
        wrapper.addView(notes);

        new MaterialAlertDialogBuilder(context)
                .setTitle(leadName == null
                        ? context.getString(R.string.demos_book_title)
                        : context.getString(R.string.demos_book_title_for, leadName))
                .setView(wrapper)
                .setPositiveButton(R.string.demos_book, (d, w) -> {
                    String isoDate = pickedDate[0] == null ? "" : pickedDate[0];
                    if (isoDate.isEmpty()) {
                        host.onFailed(context.getString(R.string.demos_date_required));
                        return;
                    }
                    int teamIndex = teamPicker.getSelectedItemPosition() - 1;
                    String teamId = teamIndex >= 0 && teamIndex < teams.size()
                            ? teams.get(teamIndex).id : null;
                    String hhmm = pickedTime[0] == null ? "" : pickedTime[0];
                    String note = notes.getText() == null ? ""
                            : notes.getText().toString().trim();
                    repository.book(new DemoRequests.Create(leadId, isoDate,
                                    hhmm.isEmpty() ? null : hhmm, teamId,
                                    note.isEmpty() ? null : note),
                            (RepoCallback<com.yuvipep.app.core.net.dto.DemoDto>) result ->
                                    reportOutcome(context, result, host));
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    /** A read-only, tappable field that looks like an input row and opens a
     * picker on tap. Shows {@code hint} until a value is chosen. */
    @NonNull
    private static TextView pickerField(@NonNull Context context, @NonNull String hint) {
        TextView field = new TextView(context);
        field.setText(hint);
        float density = context.getResources().getDisplayMetrics().density;
        int padV = (int) (14 * density);
        field.setPadding(0, padV, 0, padV);
        field.setClickable(true);
        field.setFocusable(true);
        field.setTextAppearance(
                com.google.android.material.R.style.TextAppearance_Material3_BodyLarge);
        TypedValue tv = new TypedValue();
        if (context.getTheme().resolveAttribute(
                android.R.attr.selectableItemBackground, tv, true)) {
            field.setBackgroundResource(tv.resourceId);
        }
        return field;
    }

    private static void reportOutcome(@NonNull Context context,
                                      @NonNull Result<com.yuvipep.app.core.net.dto.DemoDto> result,
                                      @NonNull Host host) {
        if (result.isSuccess() && result.data != null) {
            com.yuvipep.app.core.net.dto.DemoDto demo = result.data;
            StringBuilder message = new StringBuilder(context.getString(
                    R.string.demos_booked,
                    demo.date + (demo.time == null ? "" : " " + demo.time)));
            if (demo.team != null) message.append('\n').append(demo.team);
            message.append('\n').append(demo.inviteMessageId != null
                    ? context.getString(R.string.demos_booked_invite)
                    : demo.inviteNote != null ? demo.inviteNote
                    : context.getString(R.string.demos_booked_no_invite));
            if (demo.warning != null) {
                message.append("\n\n").append(context.getString(
                        R.string.demos_clash_prefix, demo.warning));
            }
            host.onBooked(message.toString());
        } else if (result.error != null) {
            host.onFailed(result.error.message);
        }
    }
}
