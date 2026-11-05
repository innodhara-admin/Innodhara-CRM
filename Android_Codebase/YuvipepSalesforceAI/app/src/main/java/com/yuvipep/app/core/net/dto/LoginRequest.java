package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

public class LoginRequest {
    @SerializedName("email") public final String email;
    @SerializedName("password") public final String password;

    public LoginRequest(String email, String password) {
        this.email = email;
        this.password = password;
    }
}
