"""Web HITL approval UI + JSON API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from opspilot.approval_queue import get_by_thread, list_pending
from opspilot.config import get_settings
from opspilot.graph import resume_incident
from opspilot.schemas import HumanApprovalDecision

router = APIRouter(tags=["approvals"])


def _check_token(authorization: str | None, x_token: str | None) -> None:
    expected = get_settings().approval_api_token
    if not expected:
        return
    provided = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif x_token:
        provided = x_token.strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid approval token")


@router.get("/api/approvals")
async def api_list_approvals(
    authorization: str | None = Header(default=None),
    x_opspilot_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(authorization, x_opspilot_token)
    items = [e.to_dict() for e in list_pending()]
    return {"count": len(items), "approvals": items}


@router.post("/api/approvals/{thread_id}/decide")
async def api_decide(
    thread_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_opspilot_token: str | None = Header(default=None),
) -> JSONResponse:
    _check_token(authorization, x_opspilot_token)
    body = await request.json()
    decision_raw = str(body.get("decision") or "").lower()
    try:
        decision = HumanApprovalDecision(decision_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="decision must be approved|rejected")

    pending = get_by_thread(thread_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="unknown thread_id")

    state = resume_incident(
        thread_id,
        {
            "request_id": pending.request_id,
            "decision": decision.value,
            "reviewer_id": str(body.get("reviewer_id") or "web-ui"),
            "notes": body.get("notes"),
        },
        persist=True,
    )
    return JSONResponse(
        {
            "status": "ok",
            "thread_id": thread_id,
            "decision": decision.value,
            "executed": state.get("execution") is not None,
            "escalated": state.get("escalation") is not None,
        }
    )


@router.get("/approvals", response_class=HTMLResponse)
async def approvals_page() -> str:
    """Minimal operator UI for pending HITL approvals."""
    items = list_pending()
    rows = []
    for e in items:
        tools = ", ".join(p.get("tool_name", "?") for p in e.proposals) or "(none)"
        rows.append(
            f"""
            <article class="card" data-thread="{e.thread_id}">
              <h2>{_esc(e.event_id[:8])}… <span class="muted">{_esc(e.source or 'unknown')}</span></h2>
              <p>{_esc(e.context_summary[:280] or 'No summary')}</p>
              <p class="muted">tools: {_esc(tools)}</p>
              <p class="muted">thread: <code>{_esc(e.thread_id)}</code></p>
              <div class="actions">
                <button onclick="decide('{e.thread_id}','approved')">Approve</button>
                <button class="danger" onclick="decide('{e.thread_id}','rejected')">Reject</button>
              </div>
            </article>
            """
        )
    body = "\n".join(rows) if rows else "<p class='empty'>No pending approvals.</p>"
    token_hint = (
        "Set header <code>X-OpsPilot-Token</code> if OPSPILOT_APPROVAL_API_TOKEN is configured."
        if get_settings().approval_api_token
        else "No approval API token configured (local/dev)."
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>OpsPilot Approvals</title>
  <style>
    :root {{ --bg:#0f1419; --panel:#1a222c; --text:#e7eef7; --muted:#8b9bb0; --ok:#3d9a6a; --bad:#c44; --accent:#4f8cff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background:
      radial-gradient(1200px 600px at 10% -10%, #1c2a3d 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #243018 0%, transparent 50%),
      var(--bg); color:var(--text); min-height:100vh; }}
    main {{ max-width:820px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
    h1 {{ font-family:"IBM Plex Serif", Georgia, serif; font-weight:600; font-size:2.2rem; letter-spacing:-0.02em; margin:0 0 .35rem; }}
    .sub {{ color:var(--muted); margin-bottom:1.75rem; }}
    .card {{ background:color-mix(in srgb, var(--panel) 92%, white 8%); border:1px solid #2a3544; border-radius:12px; padding:1.1rem 1.2rem; margin-bottom:1rem; }}
    .card h2 {{ margin:0 0 .5rem; font-size:1.05rem; }}
    .muted {{ color:var(--muted); font-size:.9rem; }}
    .actions {{ display:flex; gap:.6rem; margin-top:.85rem; }}
    button {{ background:var(--ok); color:#04140c; border:0; border-radius:8px; padding:.55rem 1rem; font-weight:600; cursor:pointer; }}
    button.danger {{ background:var(--bad); color:#fff; }}
    .empty {{ color:var(--muted); }}
    code {{ font-size:.85em; }}
  </style>
</head>
<body>
  <main>
    <h1>OpsPilot</h1>
    <p class="sub">Pending human approvals · {token_hint}</p>
    {body}
  </main>
  <script>
    async function decide(threadId, decision) {{
      const token = localStorage.getItem('opspilot_token') || '';
      const headers = {{'Content-Type':'application/json'}};
      if (token) headers['X-OpsPilot-Token'] = token;
      const res = await fetch('/api/approvals/' + threadId + '/decide', {{
        method:'POST', headers, body: JSON.stringify({{decision, reviewer_id:'web-ui'}})
      }});
      if (!res.ok) {{ alert('Failed: ' + (await res.text())); return; }}
      location.reload();
    }}
  </script>
</body>
</html>"""


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
