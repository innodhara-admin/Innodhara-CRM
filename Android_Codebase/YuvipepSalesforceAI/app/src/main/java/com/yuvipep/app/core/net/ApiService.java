package com.yuvipep.app.core.net;

import com.yuvipep.app.core.net.dto.ApprovalDto;
import com.yuvipep.app.core.net.dto.AssistantDtos;
import com.yuvipep.app.core.net.dto.MessageRequests;
import com.yuvipep.app.core.net.dto.MouDto;
import com.yuvipep.app.core.net.dto.ProposalDetailDto;
import com.yuvipep.app.core.net.dto.ProposalRequests;
import com.yuvipep.app.core.net.dto.ProposalResponses;
import com.yuvipep.app.core.net.dto.CardScanResponse;
import com.yuvipep.app.core.net.dto.ChangePasswordRequest;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.LeadCycleDto;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.core.net.dto.LeadRequests;
import com.yuvipep.app.core.net.dto.MeetingDto;
import com.yuvipep.app.core.net.dto.MeetingNotesRequest;
import com.yuvipep.app.core.net.dto.MeetingNotesResponse;
import com.yuvipep.app.core.net.dto.ConflictDto;
import com.yuvipep.app.core.net.dto.DraftMessageResponse;
import com.yuvipep.app.core.net.dto.InboundIngestRequest;
import com.yuvipep.app.core.net.dto.InboundIngestResponse;
import com.yuvipep.app.core.net.dto.PlanVersionDto;
import com.yuvipep.app.core.net.dto.ProjectDetailDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.core.net.dto.ProjectRequests;
import com.yuvipep.app.core.net.dto.ProjectResponses;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.net.dto.TaskRequests;
import com.yuvipep.app.core.net.dto.TaskResponses;
import com.yuvipep.app.core.net.dto.TimelineEventDto;
import com.yuvipep.app.core.net.dto.ChangedResponse;
import com.yuvipep.app.core.net.dto.ConfirmBatchRequest;
import com.yuvipep.app.core.net.dto.ConfirmBatchResponse;
import com.yuvipep.app.core.net.dto.DecideRequest;
import com.yuvipep.app.core.net.dto.DecideResponse;
import com.yuvipep.app.core.net.dto.DigestResponse;
import com.yuvipep.app.core.net.dto.LoginRequest;
import com.yuvipep.app.core.net.dto.LoginResponse;
import com.yuvipep.app.core.net.dto.MeResponse;
import com.yuvipep.app.core.net.dto.MeetingReviewResponse;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.core.net.dto.NotificationDto;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.RecentlyOpenedDto;
import com.yuvipep.app.core.net.dto.RelationshipClientDto;
import com.yuvipep.app.core.net.dto.RelationshipDto;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.core.net.dto.ReviewConfirmRequest;
import com.yuvipep.app.core.net.dto.ReviewConfirmResponse;
import com.yuvipep.app.core.net.dto.TriageItemDto;
import com.yuvipep.app.core.net.dto.TriageResolveRequest;
import com.yuvipep.app.core.net.dto.DemoDto;
import com.yuvipep.app.core.net.dto.DemoCalendarDto;
import com.yuvipep.app.core.net.dto.DemoRequests;
import com.yuvipep.app.core.net.dto.DemoTeamDto;
import com.yuvipep.app.core.net.dto.FollowUpDto;
import com.yuvipep.app.core.net.dto.FollowUpRequests;

import java.util.List;
import java.util.Map;

import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.http.Streaming;
import retrofit2.http.Body;
import retrofit2.http.DELETE;
import retrofit2.http.GET;
import retrofit2.http.Header;
import retrofit2.http.Multipart;
import retrofit2.http.PATCH;
import retrofit2.http.POST;
import retrofit2.http.Part;
import retrofit2.http.Path;
import retrofit2.http.Query;

/**
 * The Retrofit contract, grouped exactly like the backend routers
 * (01_BACKEND_CONTRACT). Phases append their groups here — one interface,
 * 134 endpoints when done.
 */
public interface ApiService {

    // ── 1.1 /auth — identity ─────────────────────────────────────────

    @POST("api/v1/auth/login")
    Call<LoginResponse> login(@Body LoginRequest body);

    @GET("api/v1/auth/me")
    Call<MeResponse> me();

    @POST("api/v1/auth/refresh")
    Call<LoginResponse> refresh();

    @POST("api/v1/auth/change-password")
    Call<ChangedResponse> changePassword(@Body ChangePasswordRequest body);

    // ── 1.10 Approvals & assignments ─────────────────────────────────

    @GET("api/v1/approvals")
    Call<List<ApprovalDto>> approvals(@Query("status") String status,
                                      @Query("mine") boolean mine);

    // Idempotency key is passed explicitly so an offline-queued decide and
    // its online retry share the exact same key (07 §4).
    @POST("api/v1/approvals/{id}/decide")
    Call<DecideResponse> decideApproval(@Path("id") String approvalId,
                                        @Body DecideRequest body,
                                        @Header("Idempotency-Key") String idempotencyKey);

    @GET("api/v1/assignments/proposed")
    Call<List<ProposedAssignmentDto>> proposedAssignments();

    @POST("api/v1/assignments/confirm-batch")
    Call<ConfirmBatchResponse> confirmAssignmentBatch(@Body ConfirmBatchRequest body);

    // ── 1.11 Inbound triage ──────────────────────────────────────────

    @GET("api/v1/inbound/triage")
    Call<List<TriageItemDto>> triageQueue();

    @POST("api/v1/inbound/{id}/resolve")
    Call<Map<String, Object>> resolveTriage(@Path("id") String messageId,
                                            @Body TriageResolveRequest body);

    /** "Log client reply" — a call or a WhatsApp that arrived outside the
     * system, typed or dictated in by the person who received it. */
    @POST("api/v1/inbound/ingest")
    Call<InboundIngestResponse> ingestInbound(@Body InboundIngestRequest body);

    // ── 1.4 /leads — relationships (Phase 2) ─────────────────────────

    @GET("api/v1/leads")
    Call<List<LeadDto>> leads(@Query("state") String state,
                              @Query("q") String query,
                              @Query("mine") boolean mine,
                              @Query("important") boolean important,
                              @Query("limit") int limit,
                              @Query("offset") int offset);

    @POST("api/v1/leads")
    Call<LeadDto> createLead(@Body LeadRequests.Create body);

    /** The owner picker's source: sales agents, callable by a sales lead.
     *  Declared before leadDetail here for readability only — the server is
     *  where the route order actually matters. */
    @GET("api/v1/leads/assignable-owners")
    Call<List<OrgUserDto>> assignableOwners();

    /** Leads that just came out of cold calling — the Home announcement. */
    @GET("api/v1/leads/recently-opened")
    Call<List<RecentlyOpenedDto>> recentlyOpenedLeads();

    @GET("api/v1/leads/{id}")
    Call<LeadDetailResponse> leadDetail(@Path("id") String leadId);

    @PATCH("api/v1/leads/{id}")
    Call<LeadDto> updateLead(@Path("id") String leadId,
                             @Body LeadRequests.Update body);

    @PATCH("api/v1/leads/{id}/state")
    Call<LeadDto> changeLeadState(@Path("id") String leadId,
                                  @Body LeadRequests.StateChange body);

    @POST("api/v1/leads/{id}/contacts")
    Call<ContactDto> addContact(@Path("id") String leadId,
                                @Body LeadRequests.Contact body);

    // ── Relationship management ─────────────────────────────────────────────
    // Who looks after a client once the selling is finished. Separate from the
    // lead pipeline: only the subject is the same record.

    /** The relationship manager's Home. Server orders it worst-neglected
     *  first, so the screen must not re-sort. */
    @GET("api/v1/relationships/mine")
    Call<List<RelationshipClientDto>> myRelationshipClients();

    /** The "choose myself" picker. Sales-side roles only. */
    @GET("api/v1/relationship-managers")
    Call<List<RelationshipDto.Manager>> relationshipManagers();

    /** Hand a closed client over. Empty body = let the assistant choose. */
    @POST("api/v1/leads/{id}/relationship/handover")
    Call<RelationshipDto> handToRelationshipManager(
            @Path("id") String leadId,
            @Body RelationshipDto.HandoverRequest body);

    /** Correct a bad pick — moves the manager on the same engagement. */
    @POST("api/v1/leads/{id}/relationship/manager")
    Call<RelationshipDto> reassignRelationshipManager(
            @Path("id") String leadId,
            @Body RelationshipDto.ReassignRequest body);

    /** Null engagement is the ordinary answer, not a missing record. */
    @GET("api/v1/leads/{id}/relationship")
    Call<RelationshipDto.Envelope> relationshipFor(@Path("id") String leadId);

    /** The manager agrees the client wants to buy again. Tells every sales
     *  lead; does not move the lead. */
    @POST("api/v1/leads/{id}/relationship/opportunity/accept")
    Call<Map<String, Object>> acceptOpportunity(
            @Path("id") String leadId,
            @Body RelationshipDto.OpportunityDecision body);

    /** It was politeness, not interest. Recorded, not deleted. */
    @POST("api/v1/leads/{id}/relationship/opportunity/dismiss")
    Call<Map<String, Object>> dismissOpportunity(
            @Path("id") String leadId,
            @Body RelationshipDto.OpportunityDecision body);

    /** Rounds of business with a client. Empty for almost every lead. */
    @GET("api/v1/leads/{id}/cycles")
    Call<List<LeadCycleDto>> leadCycles(@Path("id") String leadId);

    /** A sales lead gives the newly reopened round to someone. */
    @POST("api/v1/leads/{id}/cycles/{n}/owner")
    Call<LeadCycleDto> setCycleOwner(@Path("id") String leadId,
                                     @Path("n") int cycleNumber,
                                     @Body LeadCycleDto.OwnerRequest body);

    /** F58: which project does this conflict / plan belong to? Notifications
     *  carry only entity_type + entity_id, so without this a conflict tap has
     *  nothing to navigate with. */
    @GET("api/v1/projects/resolve/{entityType}/{entityId}")
    Call<com.yuvipep.app.core.net.dto.ResolvedProject> resolveProjectForEntity(
            @Path("entityType") String entityType, @Path("entityId") String entityId);

    // @Multipart belongs to contactFromCard and MUST stay glued to it — the
    // card upload sends @Part parameters, and Retrofit only discovers a missing
    // @Multipart at RUNTIME, on the first call. Splitting the two compiles
    // perfectly and then crashes the moment someone taps Capture.
    @Multipart
    @POST("api/v1/leads/{id}/contacts/from-card")
    Call<CardScanResponse> contactFromCard(@Path("id") String leadId,
                                           @Part MultipartBody.Part file,
                                           @Part("draft_intro") RequestBody draftIntro);

    @PATCH("api/v1/leads/contacts/{contactId}")
    Call<ContactDto> updateContact(@Path("contactId") String contactId,
                                   @Body LeadRequests.Contact body);

    @POST("api/v1/leads/{id}/intelligence")
    Call<Map<String, Object>> addIntelligence(@Path("id") String leadId,
                                              @Body LeadRequests.Intelligence body);

    @POST("api/v1/leads/{id}/consent")
    Call<Map<String, Object>> recordConsent(@Path("id") String leadId,
                                            @Body LeadRequests.Consent body);

    // ── 1.7 Projects (Phase 4) ────────────────────────────────────────

    @GET("api/v1/projects")
    Call<List<ProjectDto>> projects(@Query("lead_id") String leadId);

    @GET("api/v1/projects")
    Call<List<ProjectDto>> projectsPortfolio(@Query("status") String status);

    @GET("api/v1/projects/{id}")
    Call<ProjectDetailDto> project(@Path("id") String projectId);

    @GET("api/v1/projects/{id}/timeline")
    Call<List<TimelineEventDto>> projectTimeline(@Path("id") String projectId,
                                                 @Query("limit") int limit);

    @GET("api/v1/projects/{id}/plans")
    Call<List<PlanVersionDto>> projectPlans(@Path("id") String projectId);

    @POST("api/v1/projects/{id}/status")
    Call<ProjectDto> setProjectStatus(@Path("id") String projectId,
                                      @Body ProjectRequests.Status body);

    @POST("api/v1/projects/{id}/phase-shift")
    Call<Map<String, Object>> phaseShift(@Path("id") String projectId,
                                         @Body ProjectRequests.PhaseShift body);

    @GET("api/v1/projects/{id}/whats-blocking")
    Call<ProjectResponses.WhatsBlocking> whatsBlocking(@Path("id") String projectId);

    @GET("api/v1/projects/{id}/brief")
    Call<ProjectResponses.Brief> projectBrief(@Path("id") String projectId);

    @POST("api/v1/projects/{id}/stakeholders")
    Call<ProjectResponses.StakeholderSaved> addStakeholder(
            @Path("id") String projectId, @Body ProjectRequests.Stakeholder body);

    @GET("api/v1/projects/{id}/conflicts")
    Call<List<ConflictDto>> projectConflicts(@Path("id") String projectId);

    @POST("api/v1/projects/{id}/conflicts/{conflictId}/resolve")
    Call<Map<String, Object>> resolveConflict(@Path("id") String projectId,
                                              @Path("conflictId") String conflictId,
                                              @Body ProjectRequests.ResolveConflict body);

    @POST("api/v1/projects/{id}/children")
    Call<ProjectResponses.Children> createChildProjects(@Path("id") String projectId,
                                                         @Body ProjectRequests.Children body);

    @GET("api/v1/projects/{id}/weekly-report")
    Call<ProjectResponses.WeeklyReport> weeklyReport(@Path("id") String projectId,
                                                     @Query("kind") String kind);

    @POST("api/v1/projects/{id}/members")
    Call<ProjectResponses.MemberAdded> addProjectMember(@Path("id") String projectId,
                                                        @Body ProjectRequests.Member body);

    @DELETE("api/v1/projects/{id}/members/{userId}")
    Call<Map<String, Object>> removeProjectMember(@Path("id") String projectId,
                                                   @Path("userId") String userId);

    // ── 1.9/1.12 My tasks (Phase 4) ────────────────────────────────────

    @GET("api/v1/action-items")
    Call<List<TaskDto>> actionItems(@Query("status") String status,
                                    @Query("owner") String owner,
                                    @Query("lead_id") String leadId,
                                    @Query("limit") int limit,
                                    @Query("offset") int offset);

    @POST("api/v1/tasks/{id}/complete")
    Call<TaskResponses.Complete> completeTask(@Path("id") String taskId,
                                              @Body TaskRequests.Complete body);

    @POST("api/v1/tasks/{id}/decline")
    Call<TaskResponses.Decline> declineTask(@Path("id") String taskId,
                                            @Body TaskRequests.Decline body);

    @POST("api/v1/tasks/{id}/block")
    Call<Map<String, Object>> blockTask(@Path("id") String taskId,
                                        @Body TaskRequests.Block body);

    @POST("api/v1/tasks/{id}/unblock")
    Call<Map<String, Object>> unblockTask(@Path("id") String taskId);

    /** Open tasks blocked on me — the "waiting on you" Home card. */
    @GET("api/v1/action-items/waiting-on-me")
    Call<com.yuvipep.app.core.net.dto.WaitingOnMeDto> waitingOnMe();

    @POST("api/v1/tasks/{id}/progress")
    Call<Map<String, Object>> updateTaskProgress(@Path("id") String taskId,
                                                 @Body TaskRequests.Progress body);

    @POST("api/v1/tasks/{id}/new-date")
    Call<TaskResponses.NewDate> newTaskDate(@Path("id") String taskId,
                                            @Body TaskRequests.NewDate body);

    @POST("api/v1/tasks/{id}/split")
    Call<TaskResponses.Split> splitTask(@Path("id") String taskId,
                                        @Body TaskRequests.Split body);

    @POST("api/v1/tasks/{id}/vendor-promise")
    Call<Map<String, Object>> vendorPromise(@Path("id") String taskId,
                                            @Body TaskRequests.VendorPromise body);

    @POST("api/v1/tasks/{id}/vendor-slip")
    Call<Map<String, Object>> vendorSlip(@Path("id") String taskId,
                                         @Body TaskRequests.VendorSlip body);

    // ── 1.5 Meetings (Phase 2: upload, notes, pipeline, retry) ───────

    @Multipart
    @POST("api/v1/meetings/upload")
    Call<MeetingDto> uploadMeeting(@Part MultipartBody.Part file,
                                   @Part("lead_id") RequestBody leadId,
                                   @Part("consent_confirmed") RequestBody consentConfirmed,
                                   @Part("duration_seconds") RequestBody durationSeconds,
                                   @Part("title") RequestBody title,
                                   /** Null is omitted by Retrofit, which is the
                                    *  old contract exactly — only a caller that
                                    *  asks for "relationship" gets the light
                                    *  pipeline. */
                                   @Part("meeting_type") RequestBody meetingType,
                                   @Header("Idempotency-Key") String idempotencyKey);

    @POST("api/v1/meetings/notes")
    Call<MeetingNotesResponse> meetingNotes(@Body MeetingNotesRequest body);

    @GET("api/v1/meetings/{id}")
    Call<MeetingDto> meeting(@Path("id") String meetingId);

    @POST("api/v1/meetings/{id}/retry")
    Call<Map<String, Object>> retryMeeting(@Path("id") String meetingId);

    // ── 1.4 Meetings (review gate slice — the rest arrives in Phase 2) ─

    @GET("api/v1/meetings/{id}/review")
    Call<MeetingReviewResponse> meetingReview(@Path("id") String meetingId);

    @POST("api/v1/meetings/{id}/review/confirm")
    Call<ReviewConfirmResponse> confirmMeetingReview(@Path("id") String meetingId,
                                                     @Body ReviewConfirmRequest body);

    // ── 1.6 Messages (message centre + draft preview) ────────────────

    /**
     * The message centre list. `status` accepts any MessageStatus value or
     * "all"; the endpoint is org-wide and needs the send_messages permission,
     * which is why the Inbox hides this half from roles that cannot send.
     */
    @GET("api/v1/messages")
    Call<List<MessageDto>> messages(@Query("status") String status,
                                    @Query("limit") int limit,
                                    @Query("offset") int offset);

    @GET("api/v1/messages/{id}")
    Call<MessageDto> message(@Path("id") String messageId);

    /** `allowBlanks` (F30): the approver has read the "[Name]" blanks and means
     *  to send it anyway. Default false — the server refuses otherwise. */
    @POST("api/v1/messages/{id}/approve")
    Call<Map<String, Object>> approveMessage(@Path("id") String messageId,
                                             @Query("allow_blanks") boolean allowBlanks);

    @POST("api/v1/messages/{id}/reject")
    Call<Map<String, Object>> rejectMessage(@Path("id") String messageId,
                                            @Body MessageRequests.Reject body);

    @POST("api/v1/messages/draft")
    Call<DraftMessageResponse> draftMessage(@Body MessageRequests.Draft body);

    // ── 1.13 Assistant + explainability (Phase 3) ────────────────────

    @POST("api/v1/assistant/command")
    Call<AssistantDtos.CommandResponse> assistantCommand(
            @Body AssistantDtos.CommandRequest body);

    /** Replay a conversation the app has lost (process death, new device). */
    @GET("api/v1/assistant/history")
    Call<List<AssistantDtos.Turn>> assistantHistory(
            @Query("session_id") String sessionId);

    /** "New chat" that actually forgets — the backend drops the turns. */
    @DELETE("api/v1/assistant/history")
    Call<Map<String, Object>> clearAssistantHistory(
            @Query("session_id") String sessionId);

    /** Voice mode: what this server supports right now. */
    @GET("api/v1/assistant/voice/config")
    Call<AssistantDtos.VoiceConfig> voiceConfig();

    // The HTTP fallback when the voice WebSocket cannot connect. @Multipart
    // must stay glued to it — Retrofit only notices its absence at runtime.
    @Multipart
    @POST("api/v1/assistant/voice/turn")
    Call<AssistantDtos.VoiceTurnResponse> voiceTurn(
            @Part MultipartBody.Part file,
            @Part("session_id") RequestBody sessionId,
            @Part("lead_id") RequestBody leadId,
            @Part("proposal_id") RequestBody proposalId,
            @Part("meeting_id") RequestBody meetingId,
            @Part("speak") RequestBody speak,
            @Part("voice") RequestBody voice);

    /** A line in one of the server's voices, as a WAV (avatar voice samples). */
    @POST("api/v1/assistant/voice/speak")
    Call<ResponseBody> voiceSpeak(@Body AssistantDtos.SpeakRequest body);

    @GET("api/v1/why/{entityType}/{entityId}")
    Call<AssistantDtos.WhyResponse> why(@Path("entityType") String entityType,
                                        @Path("entityId") String entityId);

    // ── 1.8 /proposals (Phase 3) ─────────────────────────────────────

    @GET("api/v1/proposals/{id}")
    Call<ProposalDetailDto> proposal(@Path("id") String proposalId);

    @POST("api/v1/proposals/{id}/edit")
    Call<ProposalDetailDto> editProposal(@Path("id") String proposalId,
                                         @Body ProposalRequests.Edit body);

    @Streaming
    @GET("api/v1/proposals/{id}/download")
    Call<ResponseBody> downloadProposal(@Path("id") String proposalId,
                                        @Query("format") String format);

    @Multipart
    @POST("api/v1/proposals/{id}/upload-revision")
    Call<ProposalResponses.UploadRevision> uploadProposalRevision(
            @Path("id") String proposalId,
            @Part MultipartBody.Part file);

    @POST("api/v1/proposals/{id}/submit-review")
    Call<ProposalResponses.SubmitReview> submitProposalReview(
            @Path("id") String proposalId);

    @POST("api/v1/proposals/{id}/approve-send")
    Call<ProposalResponses.ApproveSend> approveSendProposal(
            @Path("id") String proposalId,
            @Body ProposalRequests.ApproveSend body);

    // ── 1.8a /mous (the contract pipeline) ───────────────────────────
    //
    // Beside the proposal routes, never inside them. An MOU is signed AFTER a
    // proposal is accepted, so one carried as a proposal arrives on a closed
    // deal — which is why the backend keeps them in separate tables and the
    // lead payload keeps them under separate keys.
    //
    // There is no file PATH in the payload and no route that returns one: a
    // storage key is not something this app could fetch. `download` serves the
    // bytes, and asks for a PDF the backend renders on demand when the stored
    // one is missing.

    @GET("api/v1/mous/{id}")
    Call<MouDto> mou(@Path("id") String mouId);

    @Streaming
    @GET("api/v1/mous/{id}/download")
    Call<ResponseBody> downloadMou(@Path("id") String mouId,
                                   @Query("format") String format);

    // ── 1.13 Files (org-scoped, authenticated) ───────────────────────

    @Streaming
    @GET("api/v1/files/{relPath}")
    Call<ResponseBody> file(@Path(value = "relPath", encoded = true) String relPath);

    // ── 1.13 Field dictation (speak into a text field) ───────────────

    // As with contactFromCard above, @Multipart MUST stay glued to dictate()
    // — Retrofit only discovers a missing @Multipart at RUNTIME, on the first
    // tap of a mic, and the mistake compiles perfectly until then.
    @Multipart
    @POST("api/v1/dictate")
    Call<com.yuvipep.app.core.net.dto.DictationResponse> dictate(
            @Part MultipartBody.Part file);

    // ── 1.13 Digests & notifications ─────────────────────────────────

    @GET("api/v1/digests/daily")
    Call<DigestResponse> dailyDigest();

    @GET("api/v1/notifications")
    Call<List<NotificationDto>> notifications(@Query("unread_only") boolean unreadOnly,
                                              @Query("limit") int limit,
                                              @Query("offset") int offset,
                                              @Query("since") String sinceIso);

    @POST("api/v1/notifications/{id}/read")
    Call<Map<String, Object>> markNotificationRead(@Path("id") String notificationId);

    // ── 1.2 Admin (staff directory — used by the override picker where
    //      the role holds manage_staff; hidden with an explanation elsewhere) ─

    @GET("api/v1/admin/users")
    Call<List<OrgUserDto>> orgUsers();

    // ── 1.11 /demos — scheduling & the month calendar (Phase 5) ──────

    @GET("api/v1/demos")
    Call<List<DemoDto>> demos(@Query("month") String month,
                              @Query("team_id") String teamId,
                              @Query("include_cancelled") boolean includeCancelled);

    @GET("api/v1/demos/calendar")
    Call<DemoCalendarDto> demoCalendar(@Query("year") int year,
                                       @Query("month") int month,
                                       @Query("team_id") String teamId);

    @POST("api/v1/demos")
    Call<DemoDto> scheduleDemo(@Body DemoRequests.Create body);

    @PATCH("api/v1/demos/{id}")
    Call<DemoDto> updateDemo(@Path("id") String demoId, @Body DemoRequests.Update body);

    /** Team picker source — readable by any signed-in role. */
    @GET("api/v1/admin/demo-teams")
    Call<List<DemoTeamDto>> demoTeams();

    // ── 1.11 /followups — the follow-up queue (Phase 5) ──────────────

    @GET("api/v1/followups")
    Call<List<FollowUpDto>> followups(@Query("due") String due,
                                      @Query("mine") boolean mine);

    @POST("api/v1/followups/{id}/complete")
    Call<Map<String, Object>> completeFollowup(@Path("id") String followupId,
                                               @Body FollowUpRequests.Complete body);
}
