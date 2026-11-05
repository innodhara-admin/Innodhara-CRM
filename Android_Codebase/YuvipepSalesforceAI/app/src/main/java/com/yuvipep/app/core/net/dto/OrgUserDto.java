package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** GET /admin/users row — staff directory (manage_staff roles only). */
public class OrgUserDto {
    @SerializedName("id") public String id;
    @SerializedName("email") public String email;
    @SerializedName("name") public String name;
    @SerializedName("role") public String role;
    @SerializedName("phone") public String phone;
    @SerializedName("is_active") public boolean isActive;
}
