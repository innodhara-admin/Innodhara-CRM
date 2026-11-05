package com.yuvipep.app.feature.assignments;

import androidx.annotation.NonNull;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import com.yuvipep.app.core.net.dto.ConfirmBatchRequest;
import com.yuvipep.app.core.net.dto.ConfirmBatchResponse;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.core.util.Result;
import com.yuvipep.app.feature.home.WorkflowRepository;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.inject.Inject;

import dagger.hilt.android.lifecycle.HiltViewModel;

/**
 * The assignment confirmation batch (03 §8): per-task AI reasons, optional
 * override where the role can read the staff directory, one confirm.
 */
@HiltViewModel
public class AssignmentsViewModel extends ViewModel {

    private final WorkflowRepository repository;

    private final MutableLiveData<Result<List<ProposedAssignmentDto>>> assignments =
            new MutableLiveData<>();
    private final MutableLiveData<List<OrgUserDto>> staff = new MutableLiveData<>();
    private final MutableLiveData<Result<ConfirmBatchResponse>> confirmEvent =
            new MutableLiveData<>();
    private final MutableLiveData<Map<String, OrgUserDto>> overrides =
            new MutableLiveData<>(new HashMap<>());

    @Inject
    public AssignmentsViewModel(WorkflowRepository repository) {
        this.repository = repository;
    }

    public LiveData<Result<List<ProposedAssignmentDto>>> assignments() { return assignments; }

    public LiveData<List<OrgUserDto>> staff() { return staff; }

    public LiveData<Result<ConfirmBatchResponse>> confirmEvent() { return confirmEvent; }

    public LiveData<Map<String, OrgUserDto>> overrides() { return overrides; }

    public void load() {
        assignments.setValue(Result.loading());
        repository.proposedAssignments(assignments::setValue);
        // Staff directory needs manage_staff; a 403 simply means the
        // override picker stays hidden with an explanation (05 §8).
        repository.orgUsers(result ->
                staff.setValue(result.isSuccess() ? result.data : null));
    }

    public void setOverride(@NonNull String assignmentId, @NonNull OrgUserDto user) {
        Map<String, OrgUserDto> map = new HashMap<>(overrides.getValue() != null
                ? overrides.getValue() : new HashMap<>());
        map.put(assignmentId, user);
        overrides.setValue(map);
    }

    public void confirmAll() {
        Result<List<ProposedAssignmentDto>> current = assignments.getValue();
        if (current == null || current.data == null || current.data.isEmpty()) return;
        List<String> ids = new ArrayList<>();
        for (ProposedAssignmentDto a : current.data) {
            ids.add(a.id);
        }
        Map<String, String> overrideIds = new HashMap<>();
        Map<String, OrgUserDto> map = overrides.getValue();
        if (map != null) {
            for (Map.Entry<String, OrgUserDto> entry : map.entrySet()) {
                overrideIds.put(entry.getKey(), entry.getValue().id);
            }
        }
        confirmEvent.setValue(Result.loading());
        repository.confirmAssignmentBatch(
                new ConfirmBatchRequest(ids, overrideIds), confirmEvent::setValue);
    }
}
