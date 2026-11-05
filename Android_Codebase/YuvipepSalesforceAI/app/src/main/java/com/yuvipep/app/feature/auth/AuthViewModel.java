package com.yuvipep.app.feature.auth;

import androidx.annotation.NonNull;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ChangedResponse;
import com.yuvipep.app.core.net.dto.LoginResponse;
import com.yuvipep.app.core.util.Result;

import javax.inject.Inject;

import dagger.hilt.android.lifecycle.HiltViewModel;

@HiltViewModel
public class AuthViewModel extends ViewModel {

    private final AuthRepository repository;
    private final TokenStore tokenStore;

    private final MutableLiveData<Result<LoginResponse>> loginState = new MutableLiveData<>();
    private final MutableLiveData<Result<ChangedResponse>> changeState = new MutableLiveData<>();
    private final MutableLiveData<AuthRepository.SessionState> sessionState = new MutableLiveData<>();

    @Inject
    public AuthViewModel(AuthRepository repository, TokenStore tokenStore) {
        this.repository = repository;
        this.tokenStore = tokenStore;
    }

    public LiveData<Result<LoginResponse>> loginState() { return loginState; }
    public LiveData<Result<ChangedResponse>> changeState() { return changeState; }
    public LiveData<AuthRepository.SessionState> sessionState() { return sessionState; }

    public void restoreSession() {
        repository.restoreSession(sessionState::postValue);
    }

    public void login(@NonNull String email, @NonNull String password) {
        loginState.setValue(Result.loading());
        repository.login(email, password, loginState::setValue);
    }

    public void changePassword(@NonNull String current, @NonNull String newPassword) {
        changeState.setValue(Result.loading());
        repository.changePassword(current, newPassword, changeState::setValue);
    }

    public TokenStore tokenStore() {
        return tokenStore;
    }
}
