package com.yuvipep.app.core.util;

import androidx.annotation.NonNull;

/** Repository → ViewModel result callback, always invoked on main. */
public interface RepoCallback<T> {
    void onResult(@NonNull Result<T> result);
}
