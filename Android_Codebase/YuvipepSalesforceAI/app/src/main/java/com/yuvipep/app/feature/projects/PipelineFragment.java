package com.yuvipep.app.feature.projects;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.tabs.TabLayout;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.FragmentPipelineBinding;
import com.yuvipep.app.feature.leads.LeadsListFragment;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * sales_lead's Pipeline (05 §3): "leads by state + projects by health,
 * drill into any member's view" — two familiar list screens under one tab
 * rather than a bespoke third list.
 */
@AndroidEntryPoint
public class PipelineFragment extends Fragment {

    private FragmentPipelineBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentPipelineBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.pipelineTabs.addTab(binding.pipelineTabs.newTab()
                .setText(R.string.tab_leads));
        binding.pipelineTabs.addTab(binding.pipelineTabs.newTab()
                .setText(R.string.tab_projects));
        binding.pipelineTabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                show(tab.getPosition() == 0 ? new LeadsListFragment() : new ProjectsListFragment());
            }

            @Override public void onTabUnselected(TabLayout.Tab tab) { }
            @Override public void onTabReselected(TabLayout.Tab tab) { }
        });
        if (savedInstanceState == null) {
            show(new ProjectsListFragment());
            binding.pipelineTabs.selectTab(binding.pipelineTabs.getTabAt(1));
        }
    }

    private void show(@NonNull Fragment fragment) {
        getChildFragmentManager().beginTransaction()
                .replace(binding.pipelineContainer.getId(), fragment)
                .commitAllowingStateLoss();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
