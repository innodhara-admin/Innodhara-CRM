package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** POST /meetings/notes — typed/dictated notes into the same pipeline. */
public class MeetingNotesRequest {
    @SerializedName("lead_id") public String leadId;
    public String text;
    public String title;
    @SerializedName("meeting_type") public String meetingType;
    @SerializedName("project_id") public String projectId;

    public MeetingNotesRequest(String leadId, String text, String title,
                               String meetingType) {
        this.leadId = leadId;
        this.text = text;
        this.title = title;
        this.meetingType = meetingType;
    }
}
