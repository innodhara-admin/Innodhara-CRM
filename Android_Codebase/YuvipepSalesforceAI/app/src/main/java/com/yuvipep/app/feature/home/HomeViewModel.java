package com.yuvipep.app.feature.home;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.db.CachedNotification;
import com.yuvipep.app.core.net.dto.DigestResponse;
import com.yuvipep.app.core.net.dto.MeetingReviewResponse;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.core.net.dto.RecentlyOpenedDto;
import com.yuvipep.app.core.net.dto.TriageItemDto;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.Result;
import com.yuvipep.app.feature.approvals.ApprovalsRepository;
import com.yuvipep.app.feature.leads.LeadsRepository;
import com.yuvipep.app.feature.notifications.NotificationRepository;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import javax.inject.Inject;

import dagger.hilt.android.lifecycle.HiltViewModel;

/**
 * The Home pulse: briefing + the merged Waiting-on-you feed (03 §2).
 * Approvals stream from Room (cache-first, offline-honest); assignment
 * batches, review-pending meetings and triage counts are fetched live.
 */
@HiltViewModel
public class HomeViewModel extends ViewModel {

    /** A meeting whose extracted items await human review. */
    public static final class ReviewPending {
        @NonNull public final String meetingId;
        public final int itemCount;

        ReviewPending(@NonNull String meetingId, int itemCount) {
            this.meetingId = meetingId;
            this.itemCount = itemCount;
        }
    }

    private final ApprovalsRepository approvalsRepository;
    private final WorkflowRepository workflowRepository;
    private final NotificationRepository notificationRepository;
    private final LeadsRepository leadsRepository;
    private final AppExecutors executors;
    private final com.yuvipep.app.core.net.ApiService api;

    private final MutableLiveData<Result<DigestResponse>> digest = new MutableLiveData<>();
    private final MutableLiveData<List<ProposedAssignmentDto>> assignments =
            new MutableLiveData<>();
    private final MutableLiveData<List<ReviewPending>> reviews = new MutableLiveData<>();
    private final MutableLiveData<List<TriageItemDto>> triage = new MutableLiveData<>();
    private final MutableLiveData<List<RecentlyOpenedDto>> recentlyOpened =
            new MutableLiveData<>();
    private final MutableLiveData<Result<ApprovalsRepository.DecideOutcome>> decideEvent =
            new MutableLiveData<>();
    private final MutableLiveData<Long> digestFetchedAt = new MutableLiveData<>();
    private final MutableLiveData<List<com.yuvipep.app.core.net.dto.WaitingOnMeDto.Item>>
            waitingOnMe = new MutableLiveData<>();

    @Inject
    public HomeViewModel(ApprovalsRepository approvalsRepository,
                         WorkflowRepository workflowRepository,
                         NotificationRepository notificationRepository,
                         LeadsRepository leadsRepository,
                         com.yuvipep.app.core.net.ApiService api,
                         AppExecutors executors) {
        this.approvalsRepository = approvalsRepository;
        this.workflowRepository = workflowRepository;
        this.notificationRepository = notificationRepository;
        this.leadsRepository = leadsRepository;
        this.api = api;
        this.executors = executors;
    }

    public LiveData<List<CachedApproval>> approvals() {
        return approvalsRepository.observePending();
    }

    public LiveData<Result<DigestResponse>> digest() { return digest; }

    public LiveData<Long> digestFetchedAt() { return digestFetchedAt; }

    public LiveData<List<ProposedAssignmentDto>> assignments() { return assignments; }

    public LiveData<List<ReviewPending>> reviews() { return reviews; }

    public LiveData<List<TriageItemDto>> triage() { return triage; }

    /** Leads the sales floor was told about in the last few days. */
    public LiveData<List<RecentlyOpenedDto>> recentlyOpened() { return recentlyOpened; }

    /** Colleagues' tasks blocked on me (customer ask, 21 Sep 2026). */
    public LiveData<List<com.yuvipep.app.core.net.dto.WaitingOnMeDto.Item>> waitingOnMe() {
        return waitingOnMe;
    }

    public LiveData<Integer> unreadCount() {
        return notificationRepository.observeUnreadCount();
    }

    public LiveData<Result<ApprovalsRepository.DecideOutcome>> decideEvent() {
        return decideEvent;
    }

    public void refreshAll() {
        if (digest.getValue() == null) {
            digest.setValue(Result.loading());
        }
        workflowRepository.dailyDigest(result -> {
            digest.setValue(result);
            if (result.isSuccess()) {
                digestFetchedAt.setValue(System.currentTimeMillis());
            }
        });
        approvalsRepository.refreshAsync();
        notificationRepository.refreshAsync();
        workflowRepository.proposedAssignments(result ->
                assignments.setValue(result.isSuccess() ? result.data : null));
        workflowRepository.triageQueue(result ->
                triage.setValue(result.isSuccess() ? result.data : null));
        // An older server has no such route: its 404 simply shows no card.
        workflowRepository.waitingOnMe(result ->
                waitingOnMe.setValue(result.isSuccess() && result.data != null
                        ? result.data.items : null));
        // The server decides what still counts as "recently" — the window is
        // an org setting, and it drops a lead the moment work starts on it.
        leadsRepository.recentlyOpened(result ->
                recentlyOpened.setValue(result.isSuccess() ? result.data : null));
        scanReviewPending();
    }

    /**
     * Review-pending discovery: recent meeting_processed notifications name
     * the meetings; each is checked against /meetings/{id}/review and kept
     * while items still wait (client-side merge, 01 §1.14).
     */
    private void scanReviewPending() {
        executors.io().execute(() -> {
            Set<String> meetingIds = new LinkedHashSet<>();
            for (CachedNotification n : notificationRepository.allCached()) {
                if ("meeting_processed".equals(n.kind) && n.entityId != null) {
                    meetingIds.add(n.entityId);
                }
                if (meetingIds.size() >= 8) break;
            }
            List<ReviewPending> pending = new ArrayList<>();
            for (String meetingId : meetingIds) {
                try {
                    retrofit2.Response<MeetingReviewResponse> response =
                            api.meetingReview(meetingId).execute();
                    MeetingReviewResponse body = response.body();
                    if (response.isSuccessful() && body != null
                            && "review_pending".equals(body.meetingStatus)
                            && body.items != null && !body.items.isEmpty()) {
                        pending.add(new ReviewPending(meetingId, body.items.size()));
                    }
                } catch (IOException ignored) {
                    // Offline — skip; approvals cache still serves the feed.
                }
            }
            reviews.postValue(pending);
        });
    }

    public void decide(@NonNull String approvalId, boolean approve, @Nullable String note) {
        approvalsRepository.decide(approvalId, approve, note, decideEvent::setValue);
    }

    public void dismissLocalFailure(@NonNull String approvalId) {
        approvalsRepository.dismissLocalFailure(approvalId);
    }
}
