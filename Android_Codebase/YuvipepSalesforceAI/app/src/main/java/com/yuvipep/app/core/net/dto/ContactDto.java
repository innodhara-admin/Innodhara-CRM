package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** A lead contact (manual or card-scanned). */
public class ContactDto {
    public String id;
    public String name;
    public String title;
    public String email;
    public String phone;
    @SerializedName("is_primary") public boolean isPrimary;
    @SerializedName("needs_review") public boolean needsReview;
    public String source;
    /** Only present on the card-scan response. */
    public Double confidence;
    @SerializedName("organisation_on_card") public String organisationOnCard;
}
