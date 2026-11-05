package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** POST /approvals/{id}/decide result. */
public class DecideResponse {
    @SerializedName("id") public String id;
    @SerializedName("status") public String status;
    @SerializedName("stage") public String stage;
    @SerializedName("joint_status") public String jointStatus;
    @SerializedName("chained_next") public boolean chainedNext;
}
