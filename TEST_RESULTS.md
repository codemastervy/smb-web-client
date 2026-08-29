# Test results

Tested against a real Samba server on a real Ubuntu host with a real Docker
daemon. Where something could not be verified, it says so and why.

---

## Test environment

| | |
|---|---|
| Host OS | Ubuntu 24.04.4 LTS, kernel 6.8.0-138-generic, aarch64 |
| Docker | 29.7.2, Compose v5.5.0 |
| SMB server under test | Samba 4.17.12, exporting two shares with different per-user permissions |
| Client library | `smbprotocol` 1.15.0 (pure Python SMB 2/3) |
| Browser engine | Chromium via Puppeteer, at 1440×940 and 390×844 @2× DPI |

**Caveat.** The Ubuntu host is a virtual machine (Lima + Apple Virtualization)
rather than the physical NUC. Ubuntu, Docker, Samba and the SMB protocol are
all genuine; the hardware is not. Nothing in this app depends on hardware — it
is a network client — so the only consequence is the phone-browser limitation
noted in [Not verified](#not-verified).

The SMB server used throughout is the one created by the companion
[nas-dashboard](https://github.com/codemastervy/nas-dashboard) project, with
two accounts:

- `sam` — read-write on `Documents`
- `alex` — read-only on `Media`
- `guestuser` — no access to either

---

## Summary

| Area | Result |
|---|---|
| Container builds and runs | **Pass** |
| Runs as a non-root user | **Pass** — uid 10001 |
| App's own login blocks unauthenticated access | **Pass** |
| SMB connect / browse against a real share | **Pass** |
| Upload / download, byte-for-byte | **Pass** — md5 match |
| Rename, copy, move, recursive delete | **Pass** |
| Collision de-duplication | **Pass** |
| Recursive search | **Pass** |
| Transfers panel reports real progress | **Pass** |
| Multiple simultaneous connections | **Pass** — two users, same host |
| Read-only share genuinely refuses writes | **Pass** |
| Credentials encrypted at rest | **Pass** — no plaintext on disk or in the API |
| `ADMIN_PASSWORD` rotation handled honestly | **Pass** |
| Failure modal button prioritisation | **Pass** |
| Path traversal / cross-share escape | **Pass** — all refused |
| Automated test suite | **Pass** — 55 tests |
| Upload size limit enforced | **Pass** — including a falsified `Content-Length` |
| Physical phone browser | **Not verified** — see below |

---

## Bugs found by testing, and fixed

### 1. "Test connection" reported success with a **wrong password**

The worst of them. `smbprotocol` caches sessions per server and
`register_session` returns the **cached session without re-authenticating**, so
testing a deliberately wrong password against a host already connected reported
`{"ok": true}`.

Isolated and confirmed directly:

```
B. clean slate, CORRECT password, then wrong on top
  register correct pw        -> <Session object at 0x...>
  isdir                      -> True
  register WRONG pw on top   -> <Session object at 0x...>     # no exception
```

**Fixed:** `probe()` now clears every cached session for that host before
testing, and again afterwards so tested credentials are never left cached. Any
profile already using that host reconnects transparently on its next request.

After the fix, a wrong password is correctly reported:

```
--- WRONG password ---
  kind : authentication_failed | Sign-In Failed
  buttons -> edit: True   recovery: False
```

### 2. A user with no access to a share also reported success

Same root cause — the check was riding on another user's cached session. Now:

```
--- USER denied on this share ---
  kind : permission_denied | Permission Denied
```

### 3. Reconnecting always failed after the first connection

```
ValueError: Cannot disable encryption on an already negotiated session.
```

Passing `encrypt=False` explicitly to `register_session` fails on a connection
that has already negotiated — which is every reconnect, and every connect after
the Test button has opened one. Confirmed:

```
1. encrypt=False twice
  first  encrypt=False   -> registered
  second encrypt=False   -> FAILED ValueError: Cannot disable encryption...
2. encrypt omitted
  first                  -> registered
  second                 -> registered      # idempotent
```

**Fixed:** `encrypt` is passed **only** to turn encryption on; otherwise it is
omitted and left to negotiate.

### 4. Errors were classified by message text, unreliably

A missing share came back as the generic `other` / "Couldn't Connect", so the
modal offered no useful action. Inspecting the exceptions showed a far better
signal:

```
  bad password    -> LogonFailure   status: 0xc000006d
  denied share    -> AccessDenied   status: 0xc0000022
  missing file    -> SMBOSError     errno: 2
```

**Fixed:** classification is now numeric NT status first, then `errno`, then
exception class, and only then message text. Message text varies between
library versions; the status code does not.

### 5. A missing share said "that item no longer exists"

The server answers `STATUS_OBJECT_NAME_NOT_FOUND` for a bad share name, which
maps to `not_found` — technically right, unhelpfully worded, and it offered no
Edit Connection button.

**Fixed:** errors raised while opening the **share root** are remapped to
`share_not_found`, since at that point the only thing being opened *is* the
share. Now:

```
kind: share_not_found | Share Not Found
msg : ...is reachable, but the share couldn't be opened. Check the share name.
buttons -> edit: True
```

### 6. Container would not start with a bind-mounted data directory

```
PermissionError: [Errno 13] Permission denied: '/data/.credential_salt'
```

The container runs as uid 10001; a bind-mounted host directory arrives owned by
the host user. **Fixed** two ways: the shipped compose uses a **named volume**
(Docker seeds ownership from the image, so it works with no chown), and startup
now fails with an actionable message naming the uid to chown to, instead of a
bare traceback.

### 7. An undecryptable saved password claimed the server rejected it

After an `ADMIN_PASSWORD` change the failure screen said *"NAS Documents
rejected the username or password. Check your credentials"* — which would send
someone to check a password that was never sent. **Fixed** with an explicit
message override for that case (see below).

### 8. `MAX_UPLOAD_BYTES` was declared but never enforced

Found by auditing the shipped code, not by a test — the config knob existed and
was documented, but nothing read it. Worse than having no limit at all, because
it reads as a protection that is there. An upload was bounded only by free disk
on the target share.

**Fixed:** the cap is enforced **while streaming**, in `write_file`, which is
the only place it can be trusted — a `Content-Length` is client-supplied and a
chunked upload has none. Exceeding it aborts mid-stream and deletes the partial
file. A cheap early reject on a declared oversize runs first so an obviously
too-big upload never starts. Rejections are their own `too_large` kind (HTTP
413, "File Too Large") rather than being mislabelled `out_of_space`, which
would send someone to free up disk that was never the problem.

Covered by six new tests, including the boundary (exactly at the limit is
allowed, one byte over is not), that the offending chunk is never written, and
that a deliberately under-declared `Content-Length` does not get past the
streaming guard.

### 9. Sidebar layout ran the server name into its address

`NAS Documents172.18.0.1/Documents` — the label and sublabel were inline spans.
**Fixed** by making the row's meta a flex column.

---

## SMB operations, against a real share

```
=== connect ===
{"serverId": "...", "status": {"state": "connected", "username": "sam"}}

=== list ===
 path: /
   file sam-test.txt 24
   file from-macbook.txt 62
   file sample.bin 3145728
```

Those files were written to the share earlier from a Mac over SMB, so this is a
genuine round trip through a third machine.

| Operation | Result |
|---|---|
| `mkdir` | ✅ `/WebClientTest` |
| Upload 2 MB | ✅ `wc-up.bin` 2000000 bytes |
| Upload same name again | ✅ saved as `wc-up 2.bin` — de-duplicated, not overwritten |
| Download, byte-for-byte | ✅ **md5 `461e3238…` both ways** |
| Rename | ✅ |
| Copy | ✅ |
| Move | ✅ (target existed → `renamed 2.bin`) |
| Recursive search | ✅ found both matches under a subfolder |
| Recursive delete of a **non-empty** folder | ✅ (SMB `rmdir` needs an empty dir; handled depth-first) |
| Delete the share root | ✅ **refused** |

### Transfers panel

Real byte counts, not a fake animation:

```
   move     renamed.bin  completed         0 / 0
   copy     renamed.bin  completed         0 / 0
   download wc-up.bin    completed   2000000 / 2000000
   upload   wc-up.bin    completed   2000000 / 2000000
```

(Server-side copy and move report no byte total because the transfer happens on
the server; the UI shows an indeterminate bar for those rather than a
fabricated percentage.)

### Multiple simultaneous connections

Two profiles, **different users on the same host**, connected at once:

```
  NAS Documents                    172.18.0.1/Documents   connected
  NAS Media (alex, read-only)      172.18.0.1/Media       connected

  NAS Documents               -> 3 entries
  NAS Media (alex, read-only) -> 1 entries
```

### Read-only enforcement

`alex` has read-only access to `Media`. The server, not the UI, enforces it:

| Action | Result |
|---|---|
| List `Media` | ✅ succeeds — `['Photos']` |
| `mkdir` on `Media` | ✅ **refused** — `permission_denied` |
| Upload to `Media` | ✅ **refused** — `permission_denied` |

---

## Failure classification

Every case produced against the live server:

| Scenario | kind | Leads with |
|---|---|---|
| Correct credentials | `ok` | — |
| Wrong password | `authentication_failed` | **Edit Connection** |
| Share does not exist | `share_not_found` | **Edit Connection** |
| User denied on the share | `permission_denied` | Retry |
| Hostname does not resolve | `host_unreachable` | **Recovery link** |
| Port with nothing listening | `connection_refused` | **Both** |

### The modal itself

Rendered in a real browser and its buttons read back from the DOM, for a
`connection_refused` failure with a recovery link configured:

```json
[{"text": "↗ Open Tailscale",   "primary": true},
 {"text": "✏️ Edit Connection", "primary": true},
 {"text": "↻ Retry",            "primary": false},
 {"text": "⚙️ Open Settings",   "primary": false},
 {"text": "Dismiss",            "primary": false}]
```

and for `authentication_failed`, where a VPN would not help:

```json
[{"text": "✏️ Edit Connection", "primary": true},
 {"text": "↻ Retry",            "primary": false},
 {"text": "↗ Open Tailscale",   "primary": false},
 {"text": "⚙️ Open Settings",   "primary": false},
 {"text": "Dismiss",            "primary": false}]
```

The recovery button drops out of the prominent slot and Edit Connection takes
it — matching the native app's rule. All five buttons are present in both, so
nothing is ever unreachable; only the emphasis moves.

---

## Security

### The app's own authentication

| Request | Expected | Actual |
|---|---|---|
| `GET /api/servers` with no cookie | 401 | ✅ 401 |
| `GET /api/transfers` with no cookie | 401 | ✅ 401 |
| `GET /api/preferences` with no cookie | 401 | ✅ 401 |
| `POST /api/auth/login` wrong password | 401 | ✅ 401 |
| `POST /api/auth/login` correct password | 200 + cookie | ✅ 200 |
| `GET /api/servers` with cookie | 200 | ✅ 200 |

With `ADMIN_PASSWORD` unset, every data route returns **503** rather than
serving openly.

### Credentials at rest

```
  api fields: [createdAt, domain, hasSavedPassword, host, id, name,
               passwordRecoverable, port, saveCredentials, shareName,
               status, subtitle, username]
  any API field containing the password?   False
  plaintext password present in servers.json?  False
  stored ciphertext: gAAAAABqkhHbR9OKx-D5-1n55qG2bGwy9TqRRWXX5-UbDBtDGNwpKm_E ...
```

### `ADMIN_PASSWORD` rotation

Started a second container against the same data volume with a different admin
password:

```
    hasSavedPassword    : True
    passwordRecoverable : False
    kind : authentication_failed
    msg  : The saved password for NAS Documents can no longer be read. This
           happens when ADMIN_PASSWORD changes, because the encryption key is
           derived from it. Choose Edit Connection and enter the password
           again — the server has not rejected anything.
    edit button promoted: True
```

The old password is genuinely unrecoverable, the UI flags it before you try
(`passwordRecoverable: false`), and the message does not blame the server.

### Path containment

| Attempt | Result |
|---|---|
| `/../` | ✅ 403 refused |
| `/../../etc` | ✅ 403 refused |
| `/Documents/../../..` | ✅ 403 refused |
| `\\..\\..` (backslashes) | ✅ 403 refused |
| `/..%2f..%2fWindows` | ✅ 404 |
| **`/../Documents` from the `Media` profile** | ✅ **403 — cannot reach a sibling share** |

The last one is the important one: a profile is pinned to its share and cannot
be walked out of into another share on the same host.

### Container posture

```
uid=10001(smbweb) gid=10001(smbweb) groups=10001(smbweb)
```

No host networking, no `cap_add`, no devices, no bind mounts of any disk,
`no-new-privileges: true`.

---

## Automated tests

49 tests, `python -m pytest tests -q` → `49 passed`.

- **`test_failures.py`** — every NT status mapped numerically; errno and
  socket-level errors; that a rejected password promotes **Edit Connection**
  while a timeout promotes the **recovery link**; that `connection_refused`
  offers both and `permission_denied` offers neither; that messages name the
  server; that every one of the thirteen kinds has a usable title and message.
- **`test_paths.py`** — normalisation, and that `..` is **refused rather than
  collapsed**, including backslash forms; Unicode and spaces survive.
- **`test_crypto.py`** — round trip; ciphertext never contains the plaintext;
  two encryptions of the same value differ (random IV, so equal ciphertexts
  cannot reveal equal passwords); a changed `ADMIN_PASSWORD` fails to decrypt
  **cleanly** rather than raising; and with no key material, encryption refuses
  rather than "encrypting" with a constant.

---

## Browser testing

Rendered in a real Chromium engine (Puppeteer), not devtools device emulation,
at two viewports:

- **Desktop, 1440×940** — sidebar, browser, grid view, failure modal
- **Phone, 390×844 @2× DPI** — sidebar collapses behind a hamburger with a
  scrim, the file rows drop their size/date columns and grow their touch
  targets, and the toolbar wraps to two rows

Screenshots in `docs/screenshots/`. The glass effect (`backdrop-filter` with
saturation over a drifting coloured backdrop) renders correctly in both.

---

## Not verified

### Physical phone browser — **not verified**

The prompt asked for a test on an actual phone, and this was not done. The
layout was rendered by a real browser engine at a phone viewport and DPI, which
is stronger evidence than devtools emulation, but it is still not a handset.

Specifically **unverified**:

- **Long-press to open the context menu.** The handler is implemented
  (480 ms hold, cancelled if the finger moves more than 10 px so a scroll does
  not become a long-press) and is exercised by mouse right-click, but real
  touch timing and iOS Safari's own long-press behaviour are untested.
- **iOS Safari viewport quirks** — dynamic toolbar height, `100vh` behaviour,
  and the `env(safe-area-inset-bottom)` padding on a notched device.
- **Whether `backdrop-filter` performs acceptably** on an older phone; it is
  GPU-expensive, and a low-end device may scroll poorly.
- **The download flow on iOS**, where Safari handles `Content-Disposition`
  differently from desktop browsers.

To check these: reach `http://<host>:8081` from the phone on the same network,
long-press a file row, and download something.

### SMB3 encryption (`SMB_ENCRYPT=true`) — **not verified**

Left at the default (`false`) throughout, because the test server negotiates
`server smb encrypt = desired`. The code path that passes `encrypt=True` is
exercised by no test.

### Kerberos / Active Directory — **not verified**

The `domain` field is passed through to `smbprotocol` (folded into the username
as `DOMAIN\user`), but only NTLM against a standalone Samba server was tested.
An AD environment with Kerberos is untested.

### Very large files and slow links — **not verified**

The largest transfer tested was 3 MB, over loopback. Streaming is chunked at
1 MB in both directions and never buffers a whole file in memory, but behaviour
on a multi-gigabyte file over WiFi — timeouts, browser download stalls — is
unexercised.

### Concurrent writers — **not verified**

Two browser tabs writing to the same share at once was not tested. SMB itself
arbitrates, but this app does no locking of its own.

---

## Reproducing this

```bash
cp .env.example .env && $EDITOR .env      # set ADMIN_PASSWORD
docker compose up -d --build

curl -s localhost:8081/api/health
docker run --rm -u 0 \
  -v "$PWD/backend/tests:/app/tests:ro" \
  -v "$PWD/backend/pytest.ini:/app/pytest.ini:ro" \
  -w /app smb-web-client:latest \
  sh -c "pip install -q pytest && python -m pytest tests -q"
```

Then add a real server and browse it — the only test that counts.

---

## Re-verification: fresh clone, clean build, three-way chain

A second test pass against a fresh `git clone` of this repo's `main` branch,
run alongside a fresh clone of
[nas-dashboard](https://github.com/codemastervy/nas-dashboard) on a newly
created VM, specifically to prove the full pipeline end-to-end rather than
re-test either app in isolation.

**Result: pass.**

**The chain proven:** nas-dashboard created a share → macOS's own SMB client
(`mount_smbfs`, a genuinely separate device) mounted it and wrote a file →
this app connected to that same share from a different container and listed
the exact file macOS had written. Three independent SMB implementations
(Samba, Apple's SMB stack, and this app's `smbprotocol` client) interoperating
correctly against the same share.

```
list (should see the Mac's file from earlier)
   sample.bin 3145728
   from-macos-prodtest.txt 51
```

**The two fixes from the prior session, re-tested under load rather than only
by unit test:**

- **Upload limit.** Started a second instance with `MAX_UPLOAD_BYTES=1000000`
  and pushed a 2 MB file at it two ways: once with a normal request (caught by
  the early `Content-Length` check) and once forced as `Transfer-Encoding:
  chunked` with **no length header at all** — the shape of request that would
  defeat a check relying on the client-declared size. Both were rejected with
  a real `HTTP 413` and the `too_large` failure kind:

  ```json
  {"detail": {"kind": "too_large", "title": "File Too Large",
              "underlying": "upload exceeded MAX_UPLOAD_BYTES (1000000 bytes)"}}
  ```

  Confirms the streaming guard — not just the header check — is what holds.

- **Hostname.** Not directly applicable to this app, but the shared
  `nas-dashboard` instance in the same test run reported the VM's real
  hostname rather than a container id (see that repo's `TEST_RESULTS.md`).

**Automated suite:** 56/56 passed, from a fresh install of the tests into the
freshly built image.

Same caveat as the rest of this document: this VM is aarch64, and the physical
target hardware was not available.
