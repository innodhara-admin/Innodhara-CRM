# Android handover — "Open" needs the owner's contact, and Jarvis waits for Open

Backend change dated 2026-09-24. This file tells the Android developer what changed on
the server and what to change in `YuvipepSalesforceAI`. Paths below are relative to
`app/src/main/java/com/yuvipep/app/`.

**Nothing breaks if the app is not updated.** Every API change is additive, and the
app already shows the server's refusal text. The changes below make the rule visible
*before* the salesperson taps, instead of only after.

---

## 1. What changed on the server

### Rule A — moving a lead from Cold calling to Open

`PATCH /api/v1/leads/{id}/state` with `{"state": "open"}` on a `cold_calling` lead now
succeeds only if **the lead's owner** has added **at least one contact that has a phone
number or an email address**.

| Situation | Result |
|---|---|
| No contacts at all | **422**, refused |
| Owner added a contact with only a name | **422** — a phone or an email is needed |
| Someone else (e.g. the sales lead) added the contact | **422** — only the owner's contacts count |
| Owner added a contact with a phone, an email, or both | **200**, opened |
| Owner scanned a business card that has a phone or email | **200**, counts like a typed contact |
| Lead was reassigned | The **new** owner needs their own contact |
| Org admin opens it (break-glass) | The same rule applies, so the owner's contact is still needed |
| Anything other than cold calling → open (e.g. cold calling → lost for now, open → active …) | Unchanged |

The order of checks is unchanged. A person who is not the owner still gets **403**
("Only Priya Nair owns this lead…"). They never see the contact message.

The 422 `detail` text, word for word:

- To the owner: `"<Lead> can't be opened yet. Add at least one contact with a phone number or an email address first."`
- To anyone else (the org admin): `"<Lead> can't be opened yet. Its owner, <Owner Name>, has to add at least one contact with a phone number or an email address first."`

### Rule B — Jarvis refuses sales work while a lead is in cold calling

Jarvis (`POST /api/v1/assistant/command` and voice mode) now refuses these four actions
for a lead whose state is `cold_calling`:

| Tool | Action text used in the reply |
|---|---|
| `schedule_meeting` | scheduling a meeting |
| `book_demo` | booking a demo |
| `create_proposal` | creating a proposal |
| `create_mou` | creating an MOU |

The reply is always exactly:

> `<Lead> is not in open state yet, therefore <action> is not allowed. Its owner has to move it from cold calling to open first.`

Nothing is created. For a meeting, Jarvis refuses as soon as the client is known,
whether that is in the first message or a later answer. It does not first ask for a
day and a time.

Still allowed on a cold-calling lead: notes, contacts, tasks, follow-ups, emails,
questions, and moving the state.

"Open" means "has left cold calling". Active, cold, closed and the other later states
are not blocked.

### New Jarvis tool — `add_client_contact`

Jarvis could previously add a contact only while *creating* a new client. It can now
add one to a client that already exists: *"Add Ramesh Kumar, their director, 9876543210,
as a contact for Xyz"*. It uses the same save as `POST /leads/{id}/contacts`, so a
contact the owner adds through Jarvis counts towards Rule A.

---

## 2. API additions (all additive)

### `GET /api/v1/leads/{id}` — two new top-level fields

```json
{
  "state": "cold_calling",
  "can_open": false,
  "open_blocker": "Xyz can't be opened yet. Add at least one contact with a phone number or an email address first.",
  "contacts": [
    {
      "id": "…", "name": "Ramesh Kumar", "title": "Director",
      "email": null, "phone": "9876543210",
      "is_primary": false, "needs_review": false, "source": "manual",
      "created_by": "f2a99f83…",
      "added_by_owner": true
    }
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `can_open` | boolean | `true` only when the lead is `cold_calling` **and** Rule A is met. `false` in every other state. |
| `open_blocker` | string \| null | Why it cannot be opened yet, worded for the person asking. It is phrased as an instruction when that person is the owner. `null` when it can be opened, and `null` for any lead not in cold calling. |
| `contacts[].created_by` | string \| null | User id of the person who added the contact. `null` for contacts found in meeting transcripts and for old rows that could not be matched. |
| `contacts[].added_by_owner` | boolean | `true` when that contact was added by the lead's current owner |

Existing data: on its first start, the server fills `created_by` for existing typed and
scanned contacts from the audit log. Every typed and scanned contact on the live server
was matched.

### Jarvis responses — a new `outcome` value

An action that Rule B refused looks like this:

```json
{ "tool": "book_demo", "args": {…}, "ok": false,
  "outcome": "not_allowed",
  "error": "Xyz is not in open state yet, therefore booking a demo is not allowed. Its owner has to move it from cold calling to open first." }
```

The top-level `reply` is that same sentence.

---

## 3. What to change in the app

### 3.1 DTOs (required for anything below)

`core/net/dto/LeadDetailResponse.java` — add:

```java
@SerializedName("can_open") public boolean canOpen;
/** Why "Open" would be refused right now; null when it wouldn't be. */
@SerializedName("open_blocker") public String openBlocker;
```

`core/net/dto/ContactDto.java` — add:

```java
@SerializedName("created_by") public String createdBy;
@SerializedName("added_by_owner") public boolean addedByOwner;
```

### 3.2 Lead detail → Overview tab, owner of a cold-calling lead (recommended)

`feature/leads/LeadDetailFragment.java`, in the `TAB_OVERVIEW` branch. This is the
block that currently calls
`showActions(getString(R.string.lead_open_action), this::openLead, getString(R.string.lead_drop_action), this::dropLead)`
when `LeadStates.isPreSales(lead.state) && isOwner()`.

- **If `lead.canOpen` is false:**
  - Show `lead.openBlocker` above the buttons as a hint or info row. Use the server's
    text as it is.
  - Make the primary button **"Add contact"**, calling
    `ContactSheet.showAdd(getParentFragmentManager(), leadId)`. The fragment already
    reloads on `ContactSheet.RESULT_KEY`, so `canOpen` updates after the save.
  - Keep **"Drop"** (lost for now) as the secondary button. It needs no contact.
- **If `lead.canOpen` is true:** keep today's **Open** / **Drop** buttons.

Do not rebuild the rule in the app from the contacts list. `can_open` is the server's
answer. The rule may change later, and a copy in the app would drift from it.

### 3.3 `move()` — no change needed

`move()` already shows `result.error.message` in a Snackbar. If someone taps Open anyway
(for example on a stale screen), the 422 text above appears as it is. Please leave that
in place.

### 3.4 Contacts tab (optional, nice to have)

When the lead is in cold calling, mark contacts where `addedByOwner` is true, for example
with a small "added by owner" tag. This shows the salesperson why a contact a colleague
entered does not unlock Open.

### 3.5 Assistant chat — the `not_allowed` card (recommended)

`feature/assistant/AssistantFragment.java` → `renderResponse(...)`. Today a refused
action has `ok:false`, so `actionCard(...)` gives it the red "failed" badge, and the same
sentence appears twice: once in the reply bubble and once in the card. Suggested change,
in the `for (Map<String, Object> action : response.actions)` loop, before
`actionCard(action)`:

```java
// The reply bubble already states the rule; a red "failed" card would repeat it.
if ("not_allowed".equals(action.get("outcome"))) continue;
```

Alternatively, render it as a neutral/grey card instead of the red one. Older servers
never send `not_allowed`, so this is safe to ship at any time.

### 3.6 Things that need NO change

- The Projects and Meetings tabs are already locked while cold calling
  (`showPreSalesLock()`), and "Book demo" is already hidden for pre-sales leads. Keep
  both.
- The new Jarvis tool `add_client_contact` renders through the generic action card
  (title "Add client contact"). Its result carries `saved`, `client`, and `contact`
  (`name`, `title`, `phone`, `email`). It can also carry `still_cannot_open` (a string)
  when the contact was added by someone other than the owner.
- `ContactSheet`, card scan, bulk import: unchanged. All of them save through endpoints
  that now record `created_by` automatically.

---

## 4. How to test against the server

Once this change is deployed, test against
`https://unaltered-uncommon-bottling.ngrok-free.dev` (the public URL changed on
2026-09-24).

1. As a sales lead, create a lead and assign it to agent **A**.
2. As **A**, open the lead. `can_open` is `false` and the Overview shows the hint.
   Tapping Open (if still shown) gives the 422 Snackbar.
3. As the sales lead, add a contact with a phone. As **A**, the lead still cannot be
   opened, because the contact is not A's.
4. As **A**, add a contact with only a name. It still cannot be opened.
5. As **A**, add a contact with a phone (or just an email). `can_open` becomes `true`,
   and Open works.
6. On another cold-calling lead, ask Jarvis: "schedule a meeting with <lead> tomorrow at
   11", "book a demo for <lead>", "create a proposal for <lead>", "draft the MOU for
   <lead>". Each one gets the "not in open state yet" reply, and nothing is created.
7. Ask Jarvis: "add a note for <lead>: …" and "add Ramesh, 9876543210, as a contact for
   <lead>". Both work. Then "move <lead> to open" works for the owner.
