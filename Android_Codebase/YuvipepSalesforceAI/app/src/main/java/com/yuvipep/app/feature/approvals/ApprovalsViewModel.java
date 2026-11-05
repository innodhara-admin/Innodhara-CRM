package com.yuvipep.app.feature.approvals;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MediatorLiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.core.util.Result;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.lifecycle.HiltViewModel;

/** Approvals inbox: Room-backed list + client-side entity/stage filters. */
@HiltViewModel
public class ApprovalsViewModel extends ViewModel {

    private final ApprovalsRepository repository;

    private final MutableLiveData<String> entityFilter = new MutableLiveData<>(null);
    private final MutableLiveData<Boolean> decideOnly = new MutableLiveData<>(false);
    private final MediatorLiveData<List<CachedApproval>> filtered = new MediatorLiveData<>();
    private final MutableLiveData<Result<ApprovalsRepository.DecideOutcome>> decideEvent =
            new MutableLiveData<>();

    private List<CachedApproval> latest = new ArrayList<>();

    @Inject
    public ApprovalsViewModel(ApprovalsRepository repository) {
        this.repository = repository;
        filtered.addSource(repository.observePending(), rows -> {
            latest = rows != null ? rows : new ArrayList<>();
            applyFilter();
        });
        filtered.addSource(entityFilter, f -> applyFilter());
        filtered.addSource(decideOnly, d -> applyFilter());
    }

    private void applyFilter() {
        String entity = entityFilter.getValue();
        boolean onlyDecide = Boolean.TRUE.equals(decideOnly.getValue());
        List<CachedApproval> out = new ArrayList<>();
        for (CachedApproval a : latest) {
            if (entity != null && !entity.equals(a.entityType)) continue;
            if (onlyDecide && !"decide".equals(a.stage)) continue;
            out.add(a);
        }
        filtered.setValue(out);
    }

    public LiveData<List<CachedApproval>> approvals() { return filtered; }

    public LiveData<Result<ApprovalsRepository.DecideOutcome>> decideEvent() {
        return decideEvent;
    }

    public void setEntityFilter(@Nullable String entityType) {
        entityFilter.setValue(entityType);
    }

    public void setDecideOnly(boolean value) {
        decideOnly.setValue(value);
    }

    public void refresh() {
        repository.refreshAsync();
    }

    public void decide(@NonNull String approvalId, boolean approve, @Nullable String note) {
        decide(approvalId, approve, note, false);
    }

    /** `allowBlanks` (F30): send it even though the draft still has blanks. */
    public void decide(@NonNull String approvalId, boolean approve,
                       @Nullable String note, boolean allowBlanks) {
        repository.decide(approvalId, approve, note, allowBlanks, decideEvent::setValue);
    }

    public void dismissLocalFailure(@NonNull String approvalId) {
        repository.dismissLocalFailure(approvalId);
    }

    public void approval(@NonNull String approvalId,
                         @NonNull com.yuvipep.app.core.util.RepoCallback<CachedApproval> cb) {
        repository.approval(approvalId, cb);
    }

    public void messagePreview(@NonNull String messageId,
                               @NonNull com.yuvipep.app.core.util.RepoCallback<MessageDto> cb) {
        repository.messagePreview(messageId, cb);
    }
}
