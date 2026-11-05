package com.yuvipep.app.core.db;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/**
 * The /auth/me snapshot — lets the app restore a session offline and
 * bootstrap the role UI without a network round-trip (03 §0: "offline +
 * cached session → Home in offline mode").
 */
@Entity(tableName = "cached_user")
public class CachedUser {

    @PrimaryKey
    @NonNull
    public String userId = "";

    public String email;
    public String name;
    public String role;
    public String orgId;
    public String orgName;
    public String orgSlug;
    public String orgLogoUrl;
    public String brandPrimary;
    public String brandAccent;
    public String phone;
    public String designation;
    public String department;
    public String orgTimezone;
    public boolean hasEmailAppPassword;
    public long fetchedAt;
}
