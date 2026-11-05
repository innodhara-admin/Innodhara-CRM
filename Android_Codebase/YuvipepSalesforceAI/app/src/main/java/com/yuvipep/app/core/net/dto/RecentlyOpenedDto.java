package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * GET /leads/recently-opened — one lead the owner has just taken out of cold
 * calling, announced on every sales person's Home screen for a few days.
 *
 * Not a {@link LeadDto}: the row carries the moment of the transition and the
 * owner's own words about it, which belong to the announcement rather than to
 * the lead.
 */
public class RecentlyOpenedDto {
    public String id;
    public String name;
    public String city;
    @SerializedName("owner_id") public String ownerId;
    @SerializedName("owner_name") public String ownerName;
    /** When it left cold calling — ISO-8601 UTC. */
    @SerializedName("opened_at") public String openedAt;
    /** What the owner logged when opening it. */
    public String reason;
}
