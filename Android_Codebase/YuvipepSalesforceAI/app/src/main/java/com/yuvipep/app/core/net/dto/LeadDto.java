package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** One lead as returned by /leads (list) and echoed by every lead write. */
public class LeadDto {
    public String id;
    public String name;
    public String state;
    @SerializedName("is_important") public boolean isImportant;
    @SerializedName("owner_id") public String ownerId;
    public String address;
    public String city;
    public String region;
    public String website;
    public String source;
    public String notes;
    @SerializedName("suggested_state") public String suggestedState;
    @SerializedName("suggested_state_reason") public String suggestedStateReason;
    @SerializedName("last_activity_at") public String lastActivityAt;
    @SerializedName("created_at") public String createdAt;
}
