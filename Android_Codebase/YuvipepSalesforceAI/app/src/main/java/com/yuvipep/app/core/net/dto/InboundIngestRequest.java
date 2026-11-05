package com.yuvipep.app.core.net.dto;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/**
 * POST /inbound/ingest — the "Log client reply" sheet (03 §9).
 *
 * A client who phones, or messages a personal WhatsApp, never reaches the
 * system on their own. Typing what they said in here puts it through exactly
 * the same understanding and routing as an email that arrived by itself, so
 * the reply is never lost just because it came in through a person.
 */
public class InboundIngestRequest {
    @SerializedName("channel") public String channel;
    @SerializedName("from_address") public String fromAddress;
    @SerializedName("to_address") @Nullable public String toAddress;
    @SerializedName("subject") @Nullable public String subject;
    @SerializedName("body") public String body;

    public InboundIngestRequest(@NonNull String channel, @NonNull String fromAddress,
                                @Nullable String subject, @NonNull String body) {
        this.channel = channel;
        this.fromAddress = fromAddress;
        this.subject = subject;
        this.body = body;
    }
}
