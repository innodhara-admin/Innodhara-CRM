"""Capture real backend responses as Android contract fixtures.

Written to app/src/test/resources/contract/. The Android suite parses each one
with the app's own Gson DTOs, so a backend rename shows up as a failing JVM
test instead of a silently-null field on a screen.

Every list fixture must have at least one row: an empty array validates under
any shape and would prove nothing.
"""
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("BACKEND_BASE", "http://127.0.0.1:9011") + "/api/v1"
OUT = pathlib.Path(
    "C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI"
    "/app/src/test/resources/contract"
)
# The running server prints its temp directory on the first line of its log.
# Point this at that log, or set BACKEND_TMPDIR.
LOG = pathlib.Path(os.environ.get("BACKEND_LOG", "backend_out.log"))


def call(method, path, body=None, tok=None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if tok:
        headers["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def new_id():
    return uuid.uuid4().hex


_, s = call("POST", "/auth/login",
            {"email": "auditsuper@platform-example.com", "password": "AuditSuper@123"})
SUPER = json.loads(s)["access_token"]

n = "ctr%d" % (int(time.time() * 1000) % 100000000)
_, raw = call("POST", "/orgs", {
    "name": "Contract Org " + n, "slug": "org-" + n,
    "email_domain": n + ".example.com",
    "admin_email": "admin@" + n + ".example.com", "admin_name": "Contract Admin"}, SUPER)
org = json.loads(raw)
ORG_ID = org["id"]
_, raw = call("POST", "/auth/login",
              {"email": org["admin_email"], "password": org["admin_temp_password"]})
tmp = json.loads(raw)["access_token"]
call("POST", "/auth/change-password",
     {"current_password": org["admin_temp_password"], "new_password": "Contract@2026"}, tmp)
_, login_raw = call("POST", "/auth/login",
                    {"email": org["admin_email"], "password": "Contract@2026"})
login = json.loads(login_raw)
TOK = login["access_token"]
ADMIN_UID = login["user_id"]
print("org:", ORG_ID)

# ── seed through the API where a route exists ───────────────────────────────
_, raw = call("POST", "/admin/users", {
    "email": "tech@" + n + ".example.com", "name": "Tech Person",
    "role": "operations_agent", "department": "operations",
    "designation": "Engineer"}, TOK)
UID = json.loads(raw)["id"]
call("POST", "/skills", {"user_id": UID, "skill": "rack-and-stack", "level": "expert"}, TOK)

_, raw = call("POST", "/admin/programs",
              {"name": "Datacentre Build", "code": "DCB", "description": "Full build"}, TOK)
PID = json.loads(raw)["id"]
call("POST", "/admin/programs/" + PID + "/pricing", {"currency": "INR", "items": [
    {"code": "rack", "label": "Rack", "unit": "each", "unit_price": 50000,
     "default_quantity": 4}]}, TOK)
call("POST", "/admin/programs/" + PID + "/proposal-templates", {
    "name": "Standard",
    "body_md": "# Proposal for {{client_name}}\n\nWe will build it well."}, TOK)
for kind, channel in (("intro", "email"), ("follow_up", "email")):
    call("POST", "/admin/message-templates", {
        "kind": kind, "channel": channel, "name": kind + " " + channel,
        "subject": "A subject line",
        "body": "Dear {{client_name}}, this is the " + kind + "."}, TOK)
call("POST", "/admin/demo-teams",
     {"name": "Demo Crew", "member_ids": [UID], "lead_user_id": UID}, TOK)
call("POST", "/vendors", {"name": "Cable Co", "category": "cabling",
                          "contact_name": "Ravi", "phone": "9999999999",
                          "email": "ravi@cableco.example.com"}, TOK)

_, raw = call("POST", "/leads", {"name": "Meridian Datacentre", "city": "Pune"}, TOK)
LEAD_ID = json.loads(raw)["id"]
call("POST", "/leads/" + LEAD_ID + "/contacts", {
    "name": "Anita Rao", "email": "anita@meridian.example.com",
    "phone": "9800000000", "designation": "Head of Infrastructure"}, TOK)
st, _ = call("POST", "/followups", {
    "lead_id": LEAD_ID, "due_date": "2026-08-27", "channel": "email",
    "note": "Check the rack count"}, TOK)
print("  seed followup ->", st)
st, _ = call("POST", "/demos", {
    "lead_id": LEAD_ID, "scheduled_date": "2026-09-10",
    "scheduled_time": "11:00", "mode": "onsite"}, TOK)
print("  seed demo ->", st)

# ── a project, its task and a proposed assignment, written straight in ──────
# There is no POST /projects — the planner builds one from a meeting — and this
# script is about response SHAPES, not about how a project comes to exist.
tmpdir = os.environ.get("BACKEND_TMPDIR")
if not tmpdir:
    tmpdir = re.search(r"TMPDIR: (.+)", LOG.read_text(encoding="utf-8")).group(1).strip()
DB = pathlib.Path(tmpdir) / "audit.db"
print("  seeding directly into", DB)
now = dt.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
con = sqlite3.connect(str(DB))
cur = con.cursor()
PROJ = new_id()
cur.execute(
    "INSERT INTO projects (id, org_id, lead_id, name, objective, status, health,"
    " currency, current_plan_version, created_at, updated_at)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    (PROJ, ORG_ID, LEAD_ID, "Meridian Hall A", "Commission 40 racks",
     "delivery", "on_track", "INR", 1, now, now))
TASK = new_id()
cur.execute(
    "INSERT INTO action_items (id, org_id, lead_id, project_id, title, description,"
    " phase, required_skill, priority, status, assignee_id, due_date, blocked,"
    " visible_to_client, source, depends_on_ids, assign_on, progress_percent,"
    " reminder_level, created_at, updated_at)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (TASK, ORG_ID, LEAD_ID, PROJ, "Rack the kit", "Install and label 40 racks",
     "delivery", "rack-and-stack", "P1", "open", ADMIN_UID,
     "2026-08-27 20:00:00", 0, 1, "meeting", "[]", "plan_activation", 0, 0,
     now, now))
cur.execute(
    "INSERT INTO assignments (id, org_id, action_item_id, to_user_id, reason,"
    " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
    (new_id(), ORG_ID, TASK, UID, "best skill match", "proposed", now, now))
con.commit()
con.close()
print("  project + task + proposed assignment seeded")

CAPTURES = [
    ("me", "/auth/me"),
    ("action_items", "/action-items"),
    ("notifications", "/notifications"),
    ("digest_daily", "/digests/daily"),
    ("admin_users", "/admin/users"),
    ("leads", "/leads"),
    ("lead_detail", "/leads/" + LEAD_ID),
    ("projects", "/projects"),
    ("project_detail", "/projects/" + PROJ),
    ("approvals", "/approvals"),
    ("messages", "/messages"),
    ("demos", "/demos"),
    ("demos_calendar", "/demos/calendar?year=2026&month=9"),
    ("followups", "/followups?due=all"),
    ("admin_demo_teams", "/admin/demo-teams"),
    ("assignments_proposed", "/assignments/proposed"),
]

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "login.json").write_text(login_raw, encoding="utf-8")
print("  login.json  (from POST /auth/login)")
written = 1
for name, path in CAPTURES:
    status, text = call("GET", path, tok=TOK)
    if status != 200:
        print("  !! %s: HTTP %s %s" % (name, status, text[:130]))
        continue
    (OUT / (name + ".json")).write_text(text, encoding="utf-8")
    parsed = json.loads(text)
    size = len(parsed) if isinstance(parsed, list) else "obj"
    print("  %s.json  (%s)" % (name, size))
    written += 1

empty = []
for f in sorted(OUT.glob("*.json")):
    parsed = json.loads(f.read_text(encoding="utf-8"))
    if isinstance(parsed, list) and not parsed:
        empty.append(f.name)
print("\n%d fixtures written to %s" % (written, OUT))
if empty:
    print("EMPTY (prove nothing, must be seeded):", ", ".join(empty))
    sys.exit(1)
print("every list fixture has at least one row")
