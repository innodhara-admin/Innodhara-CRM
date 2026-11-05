package com.yuvipep.app.feature.tasks;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import com.yuvipep.app.core.net.dto.TaskDto;

import org.junit.Test;

/**
 * A task card names its client (customer ask, 21 Sep 2026): the school shows
 * even when the task also belongs to a project, and only when there is a lead
 * to open, because the chip is a way into that lead.
 */
public class TaskClientTest {

    private static TaskDto task(String leadId, String school, String project) {
        TaskDto t = new TaskDto();
        t.leadId = leadId;
        t.leadName = school;
        t.projectName = project;
        return t;
    }

    @Test
    public void schoolShowsEvenWhenTheTaskHasAProject() {
        assertEquals("ABC School", MyTasksAdapter.clientOf(task("L1", "ABC School", "Onboarding")));
    }

    @Test
    public void noLeadMeansNoChip() {
        assertNull(MyTasksAdapter.clientOf(task(null, "ABC School", null)));
    }

    @Test
    public void blankSchoolMeansNoChip() {
        assertNull(MyTasksAdapter.clientOf(task("L1", "  ", null)));
        assertNull(MyTasksAdapter.clientOf(task("L1", null, null)));
    }

    @Test
    public void schoolIsTrimmed() {
        assertEquals("ABC School", MyTasksAdapter.clientOf(task("L1", " ABC School ", null)));
    }

    @Test
    public void metaNoLongerRepeatsTheSchool() {
        // The chip carries the school; the meta line carries the project.
        assertEquals("Onboarding", MyTasksAdapter.contextOf(task("L1", "ABC School", "Onboarding")));
        assertNull(MyTasksAdapter.contextOf(task("L1", "ABC School", null)));
        // No lead to open, so no chip: the school stays in the meta line.
        assertEquals("ABC School", MyTasksAdapter.contextOf(task(null, "ABC School", null)));
    }
}
