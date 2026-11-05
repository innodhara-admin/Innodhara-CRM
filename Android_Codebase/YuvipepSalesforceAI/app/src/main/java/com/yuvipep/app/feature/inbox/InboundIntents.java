package com.yuvipep.app.feature.inbox;

/**
 * The intent vocabulary the backend routes on (app/core/constants.py
 * InboundIntent). The server validates whatever is sent and refuses anything
 * outside this list, so the picker offers exactly these — a made-up value
 * would route nowhere.
 *
 * Labels are humanised generically at the call site, the way lead states are,
 * so a value added server-side still renders sensibly if it reaches a card
 * before this list catches up.
 */
public final class InboundIntents {

    public static final String[] ALL = {
            "question", "change_request", "approval", "rejection", "complaint",
            "payment_info", "scheduling", "acknowledgement", "unknown",
    };

    private InboundIntents() {
    }
}
