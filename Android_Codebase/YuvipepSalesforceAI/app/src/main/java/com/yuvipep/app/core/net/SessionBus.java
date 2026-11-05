package com.yuvipep.app.core.net;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import javax.inject.Inject;
import javax.inject.Singleton;

/**
 * One-shot session-expired signal: AuthInterceptor posts it on a real 401,
 * MainActivity observes it and returns to AuthActivity (09 §1).
 */
@Singleton
public class SessionBus {

    private final MutableLiveData<Boolean> sessionExpired = new MutableLiveData<>(false);

    @Inject
    public SessionBus() {
    }

    public LiveData<Boolean> sessionExpired() {
        return sessionExpired;
    }

    public void notifySessionExpired() {
        sessionExpired.postValue(true);
    }

    /** Called after the expiry has been handled (user routed to login). */
    public void reset() {
        sessionExpired.postValue(false);
    }
}
