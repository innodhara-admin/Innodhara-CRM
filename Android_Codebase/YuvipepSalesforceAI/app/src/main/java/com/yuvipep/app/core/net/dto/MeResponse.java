package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.Map;

/** Mirror of the backend's MeResponse incl. G7 org branding. */
public class MeResponse {
    @SerializedName("user_id") public String userId;
    @SerializedName("email") public String email;
    @SerializedName("name") public String name;
    @SerializedName("role") public String role;
    @SerializedName("org_id") public String orgId;
    @SerializedName("org_name") public String orgName;
    @SerializedName("phone") public String phone;
    @SerializedName("has_email_app_password") public boolean hasEmailAppPassword;
    @SerializedName("org_slug") public String orgSlug;
    @SerializedName("org_logo_url") public String orgLogoUrl;
    @SerializedName("org_brand_colors") public Map<String, String> orgBrandColors;
    @SerializedName("designation") public String designation;
    @SerializedName("department") public String department;
    /** The zone this organisation reckons dates in. Dates are bucketed in
     *  it rather than in the phone's, so the app and the server never name
     *  different days for the same row. Null on an older backend, which
     *  {@link com.yuvipep.app.core.util.WorkDay#zoneOf} reads as "use the
     *  device". */
    @SerializedName("org_timezone") public String orgTimezone;
}
