package com.yuvipep.app.feature.notifications;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.ViewModel;

import com.yuvipep.app.core.db.CachedNotification;

import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.lifecycle.HiltViewModel;

@HiltViewModel
public class NotificationsViewModel extends ViewModel {

    private final NotificationRepository repository;

    @Inject
    public NotificationsViewModel(NotificationRepository repository) {
        this.repository = repository;
    }

    public LiveData<List<CachedNotification>> notifications() {
        return repository.observeAll();
    }

    public LiveData<Integer> unreadCount() {
        return repository.observeUnreadCount();
    }

    public void refresh() {
        repository.refreshAsync();
    }

    public void markRead(String id) {
        repository.markRead(id);
    }
}
