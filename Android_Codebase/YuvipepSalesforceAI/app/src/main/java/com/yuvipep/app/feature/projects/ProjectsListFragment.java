package com.yuvipep.app.feature.projects;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.chip.Chip;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.databinding.FragmentProjectsListBinding;
import com.yuvipep.app.databinding.ItemProjectBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Project portfolio (03 §6): health badge, status, value, sorted health-first
 * (delayed → at_risk → on_track → unknown) so trouble surfaces on top.
 */
@AndroidEntryPoint
public class ProjectsListFragment extends Fragment {

    @Inject ProjectsRepository repository;

    private FragmentProjectsListBinding binding;
    private final List<ProjectDto> projects = new ArrayList<>();
    private final Adapter adapter = new Adapter();
    @Nullable private String statusFilter;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentProjectsListBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.projectList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.projectList.setAdapter(adapter);
        binding.swipeRefresh.setOnRefreshListener(this::load);
        buildChips();
    }

    @Override
    public void onResume() {
        super.onResume();
        load();
    }

    private void buildChips() {
        for (String status : ProjectStates.STATUSES) {
            Chip chip = new Chip(requireContext(), null,
                    com.google.android.material.R.attr.chipStyle);
            chip.setText(LeadStates.label(status));
            chip.setCheckable(true);
            chip.setTag(status);
            chip.setOnCheckedChangeListener((c, checked) -> {
                if (checked) {
                    statusFilter = status;
                    for (int i = 0; i < binding.filterChips.getChildCount(); i++) {
                        View child = binding.filterChips.getChildAt(i);
                        if (child instanceof Chip && child != c) {
                            ((Chip) child).setChecked(false);
                        }
                    }
                } else if (status.equals(statusFilter)) {
                    statusFilter = null;
                }
                load();
            });
            binding.filterChips.addView(chip);
        }
    }

    private void load() {
        if (binding == null) return;
        if (projects.isEmpty()) binding.stateView.showLoading();
        repository.portfolio(statusFilter, result -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(false);
            if (result.isSuccess() && result.data != null) {
                projects.clear();
                projects.addAll(result.data);
                projects.sort(Comparator.comparingInt(ProjectsListFragment::healthRank));
                adapter.notifyDataSetChanged();
                if (projects.isEmpty()) {
                    binding.stateView.showEmpty(getString(R.string.projects_empty_title),
                            getString(R.string.projects_empty_body),
                            R.drawable.ic_tab_folder, null, null);
                } else {
                    binding.stateView.hide();
                }
            } else if (result.isError() && result.error != null) {
                if (projects.isEmpty()) {
                    binding.stateView.showError(result.error.message, this::load);
                } else {
                    com.google.android.material.snackbar.Snackbar.make(binding.getRoot(),
                            result.error.message,
                            com.google.android.material.snackbar.Snackbar.LENGTH_LONG).show();
                }
            }
        });
    }

    private static int healthRank(@NonNull ProjectDto p) {
        if ("delayed".equals(p.health)) return 0;
        if ("at_risk".equals(p.health)) return 1;
        if ("on_track".equals(p.health)) return 2;
        return 3;
    }

    private void open(@NonNull String projectId) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(ProjectDetailFragment.create(projectId));
        }
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemProjectBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(projects.get(position));
        }

        @Override
        public int getItemCount() {
            return projects.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemProjectBinding row;

            Holder(ItemProjectBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(ProjectDto project) {
                row.projectName.setText(project.name);
                row.healthDot.setBackgroundTintList(
                        ContextCompat.getColorStateList(requireContext(),
                                ProjectStates.healthColor(project.health)));

                StringBuilder meta = new StringBuilder(LeadStates.label(project.status));
                if (project.health != null) {
                    meta.append(" · ").append(LeadStates.label(project.health));
                }
                if (project.valueEstimate != null && project.valueEstimate > 0) {
                    meta.append(" · ").append(com.yuvipep.app.core.util.Money.format(
                            project.valueEstimate, project.currency));
                }
                row.projectMeta.setText(meta);

                if (project.healthReason != null && !project.healthReason.isEmpty()) {
                    row.projectHealthReason.setText(project.healthReason);
                    row.projectHealthReason.setVisibility(View.VISIBLE);
                } else {
                    row.projectHealthReason.setVisibility(View.GONE);
                }
                row.getRoot().setOnClickListener(v -> open(project.id));
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
