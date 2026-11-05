package com.yuvipep.app.core.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.Currency;
import java.util.Locale;

/**
 * Money the way the backend actually stores it: an amount plus the ISO code it
 * is denominated in (FINDINGS F31).
 *
 * <p>Before this existed the project screens formatted with a hardcoded "₹" and
 * threw the currency away, so a project priced in USD rendered as rupees. The
 * backend has carried a real per-project currency all along.
 */
public final class Money {

    private Money() {
    }

    /** "USD" → "$", "INR" → "₹"; an unknown or absent code → the code itself. */
    @NonNull
    public static String symbol(@Nullable String currencyCode) {
        if (currencyCode == null || currencyCode.trim().isEmpty()) {
            return "";
        }
        String code = currencyCode.trim().toUpperCase(Locale.ROOT);
        try {
            return Currency.getInstance(code).getSymbol(Locale.getDefault());
        } catch (IllegalArgumentException notIsoCode) {
            // An org may store something that is not an ISO 4217 code. Showing
            // it verbatim is honest; guessing a symbol for it is not.
            return code;
        }
    }

    /**
     * An amount rendered in its own currency. A symbol that resolved to a glyph
     * sits tight against the number ("$1,200"); one that stayed a code keeps a
     * space ("XAF 1,200") so it can never read as part of the figure.
     */
    @NonNull
    public static String format(double amount, @Nullable String currencyCode) {
        String symbol = symbol(currencyCode);
        String number = String.format(Locale.getDefault(), "%,.0f", amount);
        if (symbol.isEmpty()) {
            return number;
        }
        return symbol.length() <= 2 ? symbol + number : symbol + " " + number;
    }
}
