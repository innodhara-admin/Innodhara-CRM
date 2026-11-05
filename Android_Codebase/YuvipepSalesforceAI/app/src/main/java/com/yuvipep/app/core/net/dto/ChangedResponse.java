package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** {"changed": true} from POST /auth/change-password. */
public class ChangedResponse {
    @SerializedName("changed") public boolean changed;
}
