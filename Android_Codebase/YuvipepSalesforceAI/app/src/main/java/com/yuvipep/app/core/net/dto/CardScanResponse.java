package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * POST /leads/{id}/contacts/from-card — the OCR'd contact plus the intro
 * message the backend drafted (pending approval) when the scan was clean.
 */
public class CardScanResponse {

    public ContactDto contact;
    @SerializedName("intro_message") public IntroMessage introMessage;
    @SerializedName("intro_error") public String introError;
    /** F38: nothing is queued at scan time any more — an intro will be drafted
     *  from the contact the human SAVES. False when the caller asked for none. */
    @SerializedName("intro_pending") public boolean introPending;

    public static class IntroMessage {
        @SerializedName("message_id") public String messageId;
        public String channel;
        public String to;
        public String subject;
        public String body;
        public String status;
    }
}
