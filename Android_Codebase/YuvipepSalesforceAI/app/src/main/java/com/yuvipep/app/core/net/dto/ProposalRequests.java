package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** Request bodies for the /proposals routes. */
public final class ProposalRequests {

    private ProposalRequests() {
    }

    public static class Edit {
        @SerializedName("instruction") public String instruction;

        public Edit(String instruction) {
            this.instruction = instruction;
        }
    }

    public static class ApproveSend {
        @SerializedName("to_address") public String toAddress;
        @SerializedName("cc") public List<String> cc;
        @SerializedName("extra_note") public String extraNote;

        public ApproveSend(String toAddress, List<String> cc, String extraNote) {
            this.toAddress = toAddress;
            this.cc = cc;
            this.extraNote = extraNote;
        }
    }
}
