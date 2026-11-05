package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** F58: GET /projects/resolve/{type}/{id} — the project a conflict or plan
 *  belongs to, so a notification tap can reach the screen that already exists. */
public class ResolvedProject {
    @SerializedName("project_id") public String projectId;
}
