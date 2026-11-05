"""`storage.resolve` must confine a caller to its own organisation's folder.

The prefix test it used to do was a string comparison made *before* the path
was resolved, so `orgs/{mine}/../{theirs}/x` satisfied
`startswith("orgs/{mine}/")` and then resolved into the other tenant's folder.
Escaping STORAGE_DIR entirely was already refused; this was the tenant boundary
*inside* it, which is where every organisation's meeting audio, business-card
images and generated proposals live.

`GET /api/v1/files/{rel_path:path}` passes the caller's path straight in, so
these are the two levels the fix has to hold at: the function, and the route.
"""
from __future__ import annotations

import pytest

from app.core.exceptions import PermissionDeniedError
from app.services import storage
from tests.conftest import auth, create_org

MINE = "1" * 32
THEIRS = "2" * 32


def _plant(org_id: str, name: str, text: str) -> str:
    """Write a file exactly where `save_bytes` would put it."""
    rel = f"orgs/{org_id}/proposals/{name}"
    target = storage._root() / rel  # noqa: SLF001 — the same root the code uses
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return rel


def test_resolve_allows_a_path_inside_the_callers_own_folder():
    rel = _plant(MINE, "own.txt", "mine")
    assert storage.resolve(MINE, rel).read_text(encoding="utf-8") == "mine"


@pytest.mark.parametrize(
    "traversal",
    [
        "orgs/{mine}/../{theirs}/proposals/secret.txt",
        "orgs/{mine}/x/../../{theirs}/proposals/secret.txt",
        "orgs/{mine}/./../{theirs}/proposals/secret.txt",
        "orgs/{mine}/../../orgs/{theirs}/proposals/secret.txt",
    ],
)
def test_resolve_refuses_a_traversal_into_another_organisation(traversal):
    _plant(THEIRS, "secret.txt", "THEIR CONFIDENTIAL FILE")
    rel = traversal.format(mine=MINE, theirs=THEIRS)

    with pytest.raises(PermissionDeniedError):
        storage.resolve(MINE, rel)


def test_resolve_refuses_a_traversal_up_to_the_storage_root():
    root_file = storage._root() / "root_level.txt"  # noqa: SLF001
    root_file.write_text("NOT INSIDE ANY ORGANISATION", encoding="utf-8")

    with pytest.raises(PermissionDeniedError):
        storage.resolve(MINE, f"orgs/{MINE}/../../root_level.txt")


@pytest.mark.asyncio
async def test_the_files_route_does_not_serve_another_organisations_file(
    client, super_token
):
    """The whole point, end to end: one tenant's token, another tenant's file.

    The `..` is percent-encoded because an HTTP client normalises a literal one
    out of the path before it is ever sent; the server decodes it back into
    `rel_path`, which is exactly how the leak was reproduced against a live
    server.
    """
    victim = await create_org(
        client, super_token, name="Traversal Victim",
        slug="traversal-victim", domain="traversal-victim-example.com",
    )
    attacker = await create_org(
        client, super_token, name="Traversal Attacker",
        slug="traversal-attacker", domain="traversal-attacker-example.com",
    )
    rel = _plant(victim["id"], "secret.txt", "VICTIM CONFIDENTIAL FILE")

    # The victim can read its own file — otherwise this test proves nothing.
    own = await client.get(f"/api/v1/files/{rel}", headers=auth(victim["admin_token"]))
    assert own.status_code == 200, own.text
    assert own.content == b"VICTIM CONFIDENTIAL FILE"

    attack = await client.get(
        f"/api/v1/files/orgs/{attacker['id']}/%2e%2e/{victim['id']}"
        f"/proposals/secret.txt",
        headers=auth(attacker["admin_token"]),
    )
    assert attack.status_code == 403, attack.text
    assert b"VICTIM CONFIDENTIAL FILE" not in attack.content
