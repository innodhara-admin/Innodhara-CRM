package com.yuvipep.app.feature.common;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.DrawableRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.yuvipep.app.R;
import com.yuvipep.app.databinding.FragmentPlaceholderBinding;

/**
 * Empty screen for a feature that ships in a later phase. Honest — names
 * the feature and its phase instead of pretending or crashing.
 */
public class PlaceholderFragment extends Fragment {

    private static final String ARG_FEATURE = "feature";
    private static final String ARG_PHASE = "phase";
    private static final String ARG_ICON = "icon";
    private static final String ARG_BODY_OVERRIDE = "body_override";

    private FragmentPlaceholderBinding binding;

    public static PlaceholderFragment create(@NonNull String featureName,
                                             @NonNull String phase,
                                             @DrawableRes int icon) {
        return create(featureName, phase, icon, null);
    }

    public static PlaceholderFragment create(@NonNull String featureName,
                                             @NonNull String phase,
                                             @DrawableRes int icon,
                                             @Nullable String bodyOverride) {
        PlaceholderFragment fragment = new PlaceholderFragment();
        Bundle args = new Bundle();
        args.putString(ARG_FEATURE, featureName);
        args.putString(ARG_PHASE, phase);
        args.putInt(ARG_ICON, icon);
        args.putString(ARG_BODY_OVERRIDE, bodyOverride);
        fragment.setArguments(args);
        return fragment;
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentPlaceholderBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        Bundle args = requireArguments();
        String feature = args.getString(ARG_FEATURE, "");
        String phase = args.getString(ARG_PHASE, "");
        String bodyOverride = args.getString(ARG_BODY_OVERRIDE);
        String body = bodyOverride != null ? bodyOverride
                : getString(R.string.phase_placeholder_body, feature, phase);
        binding.placeholderState.showEmpty(
                getString(R.string.phase_placeholder_title),
                body,
                args.getInt(ARG_ICON, 0),
                null, null);
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
