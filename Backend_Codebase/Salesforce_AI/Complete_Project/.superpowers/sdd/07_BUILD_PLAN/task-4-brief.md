### Task 4: Widen `GET /vendors` *(change #7)*

**Files:**
- Modify: `app/api/ops.py` — `list_vendors`
- Test: `tests/test_dashboard_reads.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: each `GET /api/v1/vendors` row gains `contact_name`, `phone`, `email`.

- [ ] **Step 1: Append the failing test**

```python
async def test_vendor_contact_details_are_readable(client, org_a):
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/vendors",
        headers=auth(token),
        json={"name": "Northgate Logistics", "contact_name": "Ravi Menon",
              "phone": "+919000000010", "email": "ravi@northgate-example.com",
              "category": "transport", "notes": "Two-day lead time."},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get("/api/v1/vendors", headers=auth(token))).json()
    row = next(v for v in rows if v["name"] == "Northgate Logistics")
    assert row["contact_name"] == "Ravi Menon"
    assert row["phone"] == "+919000000010"
    assert row["email"] == "ravi@northgate-example.com"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reads.py::test_vendor_contact_details_are_readable -v`
Expected: FAIL — `KeyError: 'contact_name'`.

- [ ] **Step 3: Widen the response**

In `app/api/ops.py`, replace the return of `list_vendors`:

```python
    return [
        {
            "id": v.id,
            "name": v.name,
            "contact_name": v.contact_name,
            "phone": v.phone,
            "email": v.email,
            "category": v.category,
            "notes": v.notes,
        }
        for v in rows
    ]
```

- [ ] **Step 4: Run it and confirm it passes**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: 4 passed.

- [ ] **Step 5: Checkpoint**

`python -m pytest -q` green. Mark change #7 done.

---

