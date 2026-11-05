# 06 — Design System (professional, org-brandable, generic)

## 1. Identity

- **Material 3** foundation, dynamic-color OFF (brand consistency wins);
  light + dark themes, both first-class.
- **Org-brandable:** `organisations.brand_colors` (primary/accent) and
  logo tint the header, buttons and splash per org at runtime (Gap G7
  exposes them on /auth/me). Defaults: deep indigo `#1F3A5F` primary,
  warm amber `#E8A13D` accent (from the docs' example) — professional,
  not toy-like.
- Typography: Inter (bundled) — display 28/22, title 18, body 15,
  caption 12.5; generous line-height; numbers tabular for money.

## 2. Signature components (built once in `core/ui`, reused everywhere)

| Component | Behaviour |
|---|---|
| **ApproveBar** | The one-tap contract: full-width Approve (primary) + Reject (ghost) + note field on reject; disabled+spinner during call; success = tick Lottie + haptic |
| **WhyChip** | small "why?" pill on every AI artifact → explanation sheet (decision, inputs, confidence meter, human-override note if any) |
| **HealthBadge** | on_track/at_risk/delayed dot+label, tap = health_reason toast/sheet |
| **StateView** | unified loading (skeletons, not spinners, for lists), empty (Lottie + one-line + primary action), error (backend message + Retry), offline (cloud icon + queued count) |
| **VoiceEditText** | every text input; mic at the end, live partial text, long-press = language hint |
| **ProvenanceLine** | "added by AI from Meeting 2 · 92% sure · why?" under AI-created rows (stakeholders, tasks, facts) |
| **StatusTrail** | horizontal chips for lifecycle states (message delivery, meeting pipeline, invoice ladder) |
| **DiffView** | plan-version diffs: +added / ~moved / −cancelled grouped, monospaced dates |
| **MoneyText** | renders backend-provided amounts/computations verbatim; lock icon when from locked pricing; never an input |
| **PersonChip** | avatar+name+influence color ring (decision_maker=solid, gatekeeper=dashed, influencer=thin) with role_at_client verbatim as subtitle |

## 3. Motion & Lottie (restraint = professional)

- Splash brand mark (≤2s) · assistant states (listening pulse, thinking
  orbit, drafting pen) · success ticks · empty states. Nothing else moves
  for decoration. All animations ≤400ms, standard easing; respects
  system "remove animations" accessibility setting.

## 4. Content voice

- Human, brief, honest — mirror backend copy style ("The brain is
  unreachable; your request is saved."). No jargon, no ALL CAPS, no
  exclamation marks in errors. Numbers always with currency code from
  org settings. Timestamps relative (<48h) then dated.

## 5. Accessibility & inclusivity

- Touch targets ≥48dp; contrast AA in both themes; TalkBack labels on
  every actionable (incl. approve bars: "Approve proposal to Nexora,
  1,26,000 rupees"); voice input as first-class alternative everywhere;
  font-scale supported to 200% (layouts tested at 1.3× and 2×);
  RTL-safe layouts (future locales).

## 6. Layout & density rules

- Single-pane phone-first; key screens get landscape/tablet enhancements
  later (calendar, dashboards). 8dp grid; cards 16dp radius; bottom
  sheets for all quick edits (thumb reach); destructive actions never in
  sheets' primary position.

## 7. Iconography & imagery

- Material Symbols Rounded, weight 500; one accent illustration set for
  empty states (consistent style, brand-tinted); org logo via Glide with
  authenticated loader; no stock photos.
