package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** GET /digests/daily — the morning briefing, backend-rendered markdown. */
public class DigestResponse {
    @SerializedName("content_md") public String contentMd;
}
