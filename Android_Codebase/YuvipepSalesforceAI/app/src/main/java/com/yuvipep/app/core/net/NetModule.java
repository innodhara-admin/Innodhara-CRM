package com.yuvipep.app.core.net;

import com.google.gson.Gson;
import com.yuvipep.app.BuildConfig;

import java.util.concurrent.TimeUnit;

import javax.inject.Singleton;

import dagger.Module;
import dagger.Provides;
import dagger.hilt.InstallIn;
import dagger.hilt.components.SingletonComponent;
import okhttp3.OkHttpClient;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/** Networking plumbing (02_ARCHITECTURE §4). */
@Module
@InstallIn(SingletonComponent.class)
public class NetModule {

    @Provides
    @Singleton
    Gson provideGson() {
        return new Gson();
    }

    @Provides
    @Singleton
    OkHttpClient provideOkHttpClient(HostSelectionInterceptor hostSelection,
                                     AuthInterceptor auth,
                                     IdempotencyInterceptor idempotency,
                                     TimeoutInterceptor timeouts) {
        OkHttpClient.Builder builder = new OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .writeTimeout(30, TimeUnit.SECONDS)
                .addInterceptor(timeouts)
                .addInterceptor(hostSelection)
                .addInterceptor(auth)
                .addInterceptor(idempotency);
        if (BuildConfig.DEBUG) {
            HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
            logging.setLevel(HttpLoggingInterceptor.Level.BASIC);
            logging.redactHeader("Authorization");
            builder.addInterceptor(logging);
        }
        return builder.build();
    }

    @Provides
    @Singleton
    Retrofit provideRetrofit(OkHttpClient client, Gson gson,
                             EnvironmentStore environmentStore) {
        // The literal base URL only seeds Retrofit; HostSelectionInterceptor
        // rewrites every request onto the runtime environment.
        String base = environmentStore.getBaseUrl();
        if (!base.endsWith("/")) base = base + "/";
        return new Retrofit.Builder()
                .baseUrl(base)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create(gson))
                .build();
    }

    @Provides
    @Singleton
    ApiService provideApiService(Retrofit retrofit) {
        return retrofit.create(ApiService.class);
    }
}
