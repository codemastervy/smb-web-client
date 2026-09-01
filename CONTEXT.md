# Context for whoever (human or AI) picks this project up next

This file is a handoff document, written assuming no memory of any prior
conversation about this repo. The README documents *what the project is and
how to use it*; this file documents *why it's built the way it is, what's
been verified, and what hasn't*.

---

## What this is, in one paragraph

A self-hosted SMB *client* with a web UI — a web port of the native
[Simple SMB File Browser](https://github.com/codemastervy/simple-smb-file-browser)
iOS/macOS app, so shares are reachable from a phone browser without
installing anything. It is a client only: it connects **out** to SMB
servers and never hosts, creates, or manages a share itself. The companion
project [nas-dashboard](https://github.com/codemastervy/nas-dashboard) is
the thing that *creates* shares; the two are deliberately kept separate —
this repo has no code path that touches the host's own disks or runs an SMB
server.

## How this was built and tested

Same methodology as nas-dashboard: an ephemeral Ubuntu 24.04 + Docker VM
(Lima on macOS), used because this project's real failure modes —
`smbprotocol`'s session-caching behavior, GitHub Actions' own quirks, actual
SMB protocol interop — can't be verified any other way. The single most
convincing test done against this repo: **nas-dashboard created a real SMB
share → macOS's own SMB client (a genuinely separate device) mounted it and
wrote a file → this app, running in an entirely different container,
connected to that same share and listed the exact file macOS had written.**
Three independent SMB implementations (Samba, Apple's client, and this
app's `smbprotocol` client) interoperating correctly against the same data,
not just three isolated unit tests each passing on their own.

## Design decisions worth knowing, and why

**No mount, no root, no capabilities.** `smbprotocol` speaks SMB2/3 in pure
Python over an ordinary outbound TCP socket — there is no `mount.cifs`, no
`libsmb2`, nothing that needs `CAP_SYS_ADMIN`. The container runs as a fixed
non-root uid (10001) with `no-new-privileges: true`, no host networking, no
device passthrough. This is a real, load-bearing difference from
nas-dashboard, which genuinely cannot be made rootless (Samba's `smbd`
needs root to enforce per-user permissions) — worth knowing so nobody tries
to "fix" this project's non-root posture as if it were an oversight, or
assumes nas-dashboard's root requirement can be removed the same way.

**Errors are classified by numeric NT status code, not message text.**
`services/failures.py` maps `0xC000006D` → `authentication_failed`,
`0xC0000022` → `permission_denied`, and so on, verified against exception
attributes captured from `smbprotocol` at runtime (`.status` on
`SMBResponseException` subclasses) rather than assumed from documentation.
Message-text matching was deliberately avoided because the wording differs
between library versions while the status code does not. This classification
is what the failure screen's button prioritization is built on — a
rejected password promotes **Edit Connection**; a timeout promotes a
**recovery link**; `connection_refused` offers both, since either a
firewall or a needed VPN could explain it.

**A browser cannot launch a VPN app by URL scheme.** The native app opens
`tailscale://` directly when a connection times out. A web page cannot do
this reliably — custom schemes are blocked or silently ignored in most
browser contexts, with no way to detect success. The web version's
"recovery" action is a plain `https://` link to the provider's own web
console, opened in a new tab. This is documented in the README as a
genuine capability difference from the native app, not papered over as
equivalent.

**Saved SMB passwords are encrypted with a key derived from
`ADMIN_PASSWORD`** (PBKDF2-HMAC-SHA256, 600k iterations), never written to
disk itself. The explicit, tested consequence: **changing `ADMIN_PASSWORD`
makes every previously-saved SMB password permanently unreadable** — this
is correct behavior, not a bug, since silently keeping them readable would
mean the *old* password still unlocked them. Verified by rotating the admin
password against a real saved server profile and confirming the API
correctly reports `passwordRecoverable: false` and the failure screen says
plainly that the server never rejected anything — the stored credential
simply can't be decrypted anymore.

## Real bugs found by testing — and the pattern behind them

Full detail and exact reproduction transcripts are in `TEST_RESULTS.md`.
The short version, because — as with nas-dashboard — none of these were
caught by the pytest suite, only by actually running the thing against a
live SMB server:

1. **"Test connection" reported success against a deliberately wrong
   password.** `smbprotocol` caches sessions per (server, user) and
   `register_session` silently returns the *cached* session **without
   re-authenticating** when called again for the same target — confirmed
   directly: registering with a correct password, then registering again
   with a wrong one on top, returned the same session object with no
   exception. Fixed by explicitly dropping any cached session for a host
   before testing it, and again afterward.
2. **Every reconnect failed** with `"Cannot disable encryption on an
   already negotiated session"` — passing `encrypt=False` explicitly to
   `register_session` fails on a connection that has already negotiated,
   which is every second connection attempt to the same host. Fixed by
   passing `encrypt` only to turn it *on*, never explicitly off.
3. **A wrong share name reported the unhelpful generic "Couldn't Connect"**
   instead of a specific, actionable message — the server's
   `STATUS_OBJECT_NAME_NOT_FOUND` for a bad share name is technically
   correct but unhelpful out of context. Fixed by remapping `not_found` to
   `share_not_found` specifically when the error happened while opening the
   *share root* (the point at which only one thing could be missing).
4. **`MAX_UPLOAD_BYTES` was declared in config and documented, but nothing
   ever enforced it** — found by auditing the shipped code, not by a test
   failing. Worse than having no limit, because it read as a real
   protection. Fixed by enforcing it **while streaming**, since a
   `Content-Length` header is client-supplied and a chunked upload has none
   at all — verified the guard holds even against a deliberately
   under-declared length.
5. **The context-menu bug** — identical root cause and fix to the one
   found on nas-dashboard's real NUC deployment (same component, copied
   from the same origin): a capture-phase `document` click-dismiss listener
   fired before the menu's own buttons got their click, closing the menu
   before any action ran. Found by testing this repo's copy proactively
   once the nas-dashboard instance was reported, confirmed present with the
   same real-mouse-click Puppeteer reproduction, fixed the same way (check
   containment in the capture handler rather than relying on
   `stopPropagation()`, which can't retroactively stop something that
   already ran in an earlier phase).

## A CI/automation incident worth knowing about

Same incident, same root cause, same fix as nas-dashboard (they were built
and broken together): Dependabot auto-merge was enabled before branch
protection required CI to pass, so several unvetted dependency bumps
merged to `main`. Reverted via `git revert`; replaced with the bimonthly,
approval-gated [dependency-update-workflow](https://github.com/codemastervy/dependency-update-workflow).
Branch protection (`backend-tests`, `frontend-build`, `docker-build`,
`enforce_admins: true`) means a direct `git push` to `main` will be
rejected — go through a PR.

## Current known gaps (not bugs — genuinely unverified)

- **Physical phone browser.** Verified in a real Chromium engine at a phone
  viewport/DPI via Puppeteer (stronger than devtools emulation), but real
  touch long-press timing and iOS Safari's own quirks have never been
  checked on an actual handset.
- **SMB3 encryption (`SMB_ENCRYPT=true`)** — left at its default (`false`)
  throughout testing, since the test server negotiated encryption as
  `desired` rather than required. The code path that turns it on has no
  test coverage.
- **Kerberos / Active Directory.** The `domain` field is passed through
  (folded into the username as `DOMAIN\user`), but only NTLM against a
  standalone Samba server was ever tested.
- **Large files and slow links.** The largest transfer tested was a few
  megabytes over loopback. Streaming is chunked and never buffers a whole
  file in memory, but multi-gigabyte transfers over real WiFi —
  timeouts, browser download stalls — are unexercised.
- **Concurrent writers.** Two browser tabs writing to the same share at
  once was never tested. SMB itself arbitrates; this app does no locking
  of its own.

## If you're picking this up fresh

- Read the README's "Security model" and "Failure handling" sections
  first — they explain the two things most likely to surprise someone:
  the admin-password/encryption coupling, and why the failure screen
  emphasizes different buttons for different errors.
- Read `TEST_RESULTS.md` for exact commands and outputs behind every claim
  above, including the live three-way interop test with nas-dashboard.
- Branch protection applies to direct pushes, not just PR merges — branch,
  open a PR, wait for the three required checks, merge.
