package com.yuvipep.app.feature.notifications;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.db.CachedNotification;
import com.yuvipep.app.databinding.FragmentNotificationsBinding;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The notification center (07 §2): server-truth feed, cache-first, tap
 * marks read and deep-links to the entity.
 */
@AndroidEntryPoint
public class NotificationCenterFragment extends Fragment {

    private FragmentNotificationsBinding binding;
    private NotificationsViewModel viewModel;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentNotificationsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(this).get(NotificationsViewModel.class);

        NotificationAdapter adapter = new NotificationAdapter(this::onTap);
        binding.notificationList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.notificationList.setAdapter(adapter);

        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.swipeRefresh.setOnRefreshListener(() -> {
            viewModel.refresh();
            binding.swipeRefresh.setRefreshing(false);
        });

        viewModel.notifications().observe(getViewLifecycleOwner(), rows -> {
            adapter.submitList(rows);
            if (rows == null || rows.isEmpty()) {
                binding.stateView.showEmpty(getString(R.string.notifications_empty_title),
                        getString(R.string.notifications_empty_body),
                        R.drawable.ic_bell, null, null);
            } else {
                binding.stateView.hide();
            }
        });
    }

    @Override
    public void onResume() {
        super.onResume();
        viewModel.refresh();
    }

    private void onTap(@NonNull CachedNotification notification) {
        if (!notification.isRead) {
            viewModel.markRead(notification.id);
        }
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity())
                    .openEntity(notification.entityType, notification.entityId);
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
