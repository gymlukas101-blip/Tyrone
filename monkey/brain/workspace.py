"""Claude Console keys that aren't tied to one workspace need an `anthropic-workspace-id` header on every request.

New Console keys made with "Use an API key" can be organization-wide. Monkey detects the
"not scoped to a workspace" error, looks up your workspaces with the same key (Admin API: List Workspaces,
include_default=true), picks the Default Workspace (where Max plan credits land), saves its ID in settings
and sends it from then on. If that lookup isn't allowed, Settings has a field to paste the ID by hand.
"""
from __future__ import annotations

HEADER = "anthropic-workspace-id"
HELP = ("Your Claude key isn't tied to a workspace. Fix it in Settings → API keys: paste your workspace ID "
        "(Console → Settings → Workspaces, starts with wrkspc_) into “Claude workspace ID”, or create a new key "
        "inside a workspace (Console → Settings → Workspaces → Default → API keys).")


def needs_workspace(exc: Exception) -> bool:
    text = f"{getattr(exc, 'message', '')} {exc}".lower()
    return HEADER in text or "not scoped to a workspace" in text


def describe(exc: Exception) -> str:
    """A plain-English version of common setup errors."""
    status = getattr(exc, "status_code", None)
    text = f"{getattr(exc, 'message', '')} {exc}".lower()
    if needs_workspace(exc):
        return HELP
    if status == 401 or "invalid x-api-key" in text:
        return "Anthropic didn't accept the key. Make sure you pasted the whole key (it starts with sk-ant-)."
    if "credit balance" in text:
        return ("Your Claude API credits are used up or not claimed yet. With Claude Max: claude.ai → Settings → "
                "Billing → API credits → Claim, and link the same Console organization your key is from.")
    if status == 403:
        return "This key isn't allowed to use that model or workspace. Check the key's workspace in the Console."
    return str(getattr(exc, "message", exc))[:300]


def is_setup_error(message: str) -> bool:
    m = (message or "").lower()
    return any(s in m for s in (HEADER, "not scoped to a workspace", "invalid x-api-key", "authentication_error",
                                "credit balance", "permission_error", "isn't tied to a workspace",
                                "didn't accept the key", "credits are used up"))


def discover(client) -> tuple[str | None, str]:
    """Return (workspace_id, note). Prefers the Default Workspace; skips archived and Claude Code workspaces."""
    try:
        page = client.beta.organization.workspaces.list(include_default=True, limit=100)
        data = page.data if hasattr(page, "data") else list(page)
        items = [w for w in data if not getattr(w, "archived_at", None)]
    except Exception as exc:  # noqa: BLE001 - key may not be allowed to list workspaces
        return None, f"couldn't list workspaces ({type(exc).__name__})"
    if not items:
        return None, "no workspaces found"
    by_name = {str(getattr(w, "name", "")).strip().lower(): w for w in items}
    chosen = by_name.get("default workspace") or by_name.get("default")
    if chosen is None:
        normal = [w for w in items if "claude code" not in str(getattr(w, "name", "")).lower()]
        chosen = (normal or items)[0]
    return str(chosen.id), f"using workspace “{getattr(chosen, 'name', chosen.id)}”"
