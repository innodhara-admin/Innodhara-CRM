package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** POST /meetings/{id}/review/confirm — anything not echoed back is removed. */
public class ReviewConfirmRequest {
    @SerializedName("items") public List<Item> items;

    public ReviewConfirmRequest(List<Item> items) {
        this.items = items;
    }

    public static class Item {
        @SerializedName("id") public String id;          // null = user-added
        @SerializedName("title") public String title;
        @SerializedName("description") public String description;
        @SerializedName("keep") public boolean keep;

        public Item(String id, String title, String description, boolean keep) {
            this.id = id;
            this.title = title;
            this.description = description;
            this.keep = keep;
        }
    }
}
