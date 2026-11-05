package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** One project row (GET /projects, filterable by lead_id). */
public class ProjectDto {
    public String id;
    public String name;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("program_id") public String programId;
    public String objective;
    public String status;
    @SerializedName("status_reason") public String statusReason;
    public String health;
    @SerializedName("health_reason") public String healthReason;
    @SerializedName("sales_owner_id") public String salesOwnerId;
    @SerializedName("ops_owner_id") public String opsOwnerId;
    @SerializedName("current_plan_version") public Integer currentPlanVersion;
    @SerializedName("start_date") public String startDate;
    @SerializedName("target_end_date") public String targetEndDate;
    @SerializedName("value_estimate") public Double valueEstimate;
    /** ISO code valueEstimate is denominated in — never assume INR (F31). */
    public String currency;
    @SerializedName("parent_project_id") public String parentProjectId;
    @SerializedName("invoicing_mode") public String invoicingMode;
}
