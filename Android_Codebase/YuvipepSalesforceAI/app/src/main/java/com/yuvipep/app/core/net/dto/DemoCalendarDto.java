package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

/** GET /demos/calendar — the full-month grid (01 §1.11, 03 §11). */
public class DemoCalendarDto {
    public int year;
    public int month;
    @SerializedName("days_in_month") public int daysInMonth;
    /** ISO date → demos that day (empty list = free day). */
    public Map<String, List<DemoDto>> days;
    @SerializedName("free_days") public List<String> freeDays;
    @SerializedName("total_demos") public int totalDemos;
}
