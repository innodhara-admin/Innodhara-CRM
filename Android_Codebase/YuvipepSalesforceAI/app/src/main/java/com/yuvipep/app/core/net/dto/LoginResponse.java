package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** Mirror of the backend's LoginResponse (app/api/auth.py). */
public class LoginResponse {
    @SerializedName("access_token") public String accessToken;
    @SerializedName("token_type") public String tokenType;
    @SerializedName("user_id") public String userId;
    @SerializedName("name") public String name;
    @SerializedName("role") public String role;
    @SerializedName("org_id") public String orgId;
    @SerializedName("org_name") public String orgName;
    @SerializedName("must_change_password") public boolean mustChangePassword;
}
