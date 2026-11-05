package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import java.util.List;
import java.util.Map;

/** GET /admin/demo-teams — readable by any signed-in role (used by the
 * booking sheet's team picker; the backend gates only the writes). */
public class DemoTeamDto {
    public String id;
    public String name;
    @Nullable public List<Map<String, Object>> members;
}
