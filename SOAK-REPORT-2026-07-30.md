# Pre-release soak report — 2026-07-30

**Scope:** 5 registered agents across 3 hosts, soak window ~2026-06-06 → 2026-07-30 (longest continuous run 11 weeks).
**Method:** read-only SSH + `docker inspect` / in-container log aggregation. Manager API was unavailable (see P0-1), so `ciris-manager-client status` could not be used.

**Headline:** the agents themselves are cognitively healthy. Every serious finding is in the *surrounding* machinery — TLS renewal, restart policy, retry backoff, orphaned scheduler state, and the monitoring that was supposed to catch all of it. Four of the findings are silent failures that ran for 6–8 weeks with zero alerting.

---

## Status (updated 2026-07-30, after remediation)

| Finding | Status |
|---|---|
| P0-1 expired cert / 526 | **FIXED** — renewed to Oct 28, moved to webroot + reload hook; site back to 200 |
| P0-1 scout1 latent | **FIXED** — 0-byte renewal conf rebuilt as a real lineage, expires Oct 28 |
| P0-1 scout2 cert sync | **DEFERRED** (your call) — valid to Oct 16, now covered by `status endpoints` |
| P0-2 scout2 agent down | **OPEN** — needs `ciris-manager-client agent start` (blocked on auth) |
| P0-2 watchdog inert | **FIXED** — registry-driven, multi-server, absence detection |
| P1-1 telemetry retry | Filed CIRISAgent#933 |
| P1-2 scheduler FK loop | Filed CIRISAgent#934 |
| P1-3 shutdown livelock | Not a new finding — CIRISAgent#863, closed |
| P1-4 CIRISVerify alerts | Filed CIRISAgent#936 |
| P1-5 log hygiene | Filed CIRISAgent#935 |
| P2 status classifier | **FIXED** — patterns re-derived from production, regression-tested |

Also found and fixed while hardening, not in the original review:

- `HumanReadableFormatter` permanently mutated `record.levelname` to embed ANSI
  colour codes. A `LogRecord` is shared across handlers, so the rotating **file**
  handlers (deliberately `use_colors=False`) and the CIRISLens shipper were
  writing `\x1b[33mWARNING\x1b[0m` into their level field, and any consumer
  comparing `levelname == "WARNING"` silently stopped matching.
- `setup_logging()` called `root_logger.handlers.clear()`, destroying handlers
  owned by embedders.
- Test suite had order-dependent state leaks (env vars, module-global caches)
  that `pytest -n 4` masked by scheduling the colliding tests on different
  workers. CI now also runs a serial isolation pass.

---

## Fleet state

| Agent | Host | Container | Image | Externally reachable |
|---|---|---|---|---|
| datum | main | Up 7 weeks (healthy) | `:latest` (pulled 2026-05-20) | ❌ 526 |
| echo-core-jm2jy2 | main | Up 7 weeks (healthy) | digest `4014124cb692` (2026-04-30) | ❌ 526 |
| echo-speculative-4fc6ru | main | Up 7 weeks (healthy) | digest `4014124cb692` (2026-04-30) | ❌ 526 |
| scout-remote-test-dahrb9 | scout1 | Up 7 weeks (healthy) | `:2.7.6-stable` (2026-05-11) | ✅ 200 |
| scout-remote-test-dahrb9-002 | scout2 | **Exited (255) 3 weeks** | `:latest` | ❌ down |

Three distinct agent builds in production. No `ai.ciris.version` label is populated on any container, so version reporting has nothing to read.

---

## P0 — fix before the release goes out

### P0-1. `agents.ciris.ai` TLS cert expired 2026-06-14 (46 days). Everything behind Cloudflare is 526.

```
/manager/v1/health          → 526
/api/datum/v1/agent/status  → 526
/                           → 526
scoutapilb.ciris.ai/        → 200   (scouts unaffected)
```

**Root cause:** `/etc/letsencrypt/renewal/agents.ciris.ai.conf` has `authenticator = standalone`. Standalone binds TCP :80 to answer the ACME challenge, but `ciris-nginx` holds :80 (and :443) permanently. Every renewal attempt fails with:

> `Could not bind TCP port 80 because it is already in use by another process on this system`

`certbot.timer` is *active* and has been firing ~2×/day, failing every single time, since the nginx container first came up. The cert was originally issued during provisioning when nginx wasn't running yet — so this was latent from day one and only surfaced 90 days later at first renewal.

**Blast radius is wider than the manager API.** Agent APIs are served through the same nginx on the same vhost, so datum / echo-core / echo-speculative have been unreachable to any external consumer since June 14. They report `healthy` internally the whole time, because health is evaluated container-side and never traverses the TLS path.

**This also breaks the CD path.** GitHub Actions posts to `POST /manager/v1/updates/notify` on `agents.ciris.ai`. That endpoint currently returns 526, so the release you are about to cut cannot notify the manager.

**Same latent defect on scout1** — also `authenticator = standalone`. It renewed successfully on ~2026-07-18 purely because the nginx container happened to be down at that moment (`ciris-nginx` uptime on scout1 is 12 days, consistent with a restart in that window). It got lucky. Next renewal has the same coin-flip.

**scout2 has no renewal config at all.** `/etc/letsencrypt/renewal/` is empty; `/etc/letsencrypt/live/scoutapilb.ciris.ai/` contains hand-placed symlinks into `archive/scoutapilb.ciris.ai-0002` dated Jul 18, plus orphaned `*.pem.expired` files, and no `cert.pem`. The certs were copied over from scout1 by hand. When scout1 next renews, scout2 goes stale and roughly half of `scoutapilb` traffic starts returning 526.

**Hardening:**
1. Switch all three hosts to `authenticator = webroot` with `webroot_path` pointing at a directory nginx serves for `/.well-known/acme-challenge/`, or run the DNS-01 challenge (you already have Cloudflare API access). Never use `standalone` on a host that runs a always-on web server.
2. Add a `--deploy-hook` that reloads nginx via `docker exec ciris-nginx kill -HUP 1` (per `CLAUDE.md`, not `nginx -s reload`).
3. Give scout2 its own real renewal config instead of copied symlinks.
4. **Alert on cert expiry, not on certbot exit code.** The timer was healthy-looking and the service was failing; nobody looked. A daily `openssl x509 -checkend $((14*86400))` per origin, surfaced through `status security`, would have caught this on day one instead of day 46.
5. Add an end-to-end external probe (`https://agents.ciris.ai/manager/v1/health` → expect 200) to `status`. Every internal signal said green through 46 days of hard outage.

### P0-2. scout2's agent has been down 3 weeks and nothing noticed.

```
ExitCode=255  FinishedAt=2026-07-03T00:05:06Z
RestartPolicy=no  RestartCount=0  OOMKilled=false
```

FinishedAt lines up exactly with the Vultr maintenance reboot (host uptime 3w 6d). The host came back; the agent did not.

**Root cause, two compounding halves:**

**(a) `restart: 'no'` on every agent container.** Verified across all 5:

```
/ciris-datum                        restart=no
/ciris-echo-speculative-4fc6ru      restart=no
/ciris-echo-core-jm2jy2             restart=no
/ciris-scout-remote-test-dahrb9     restart=no
/ciris-scout-remote-test-dahrb9-002 restart=no
/ciris-gui                          restart=unless-stopped
/ciris-nginx                        restart=unless-stopped
```

Infrastructure containers restart; agents don't. It's declared that way in every generated `docker-compose.yml` (`restart: 'no'`), so this is the generator's output, not drift.

This directly contradicts the documented CD design in `CLAUDE.md`:

> *"Docker's restart policy handles container swap"*

There is no restart policy to handle it. Any deployment that relies on the container coming back by itself will leave the agent dead. Worth deciding deliberately before the release: if `restart: no` is intentional (so the manager owns lifecycle exclusively), then the CD docs and the swap mechanism need to change to match. If it isn't intentional, `unless-stopped` fixes both this and the reboot case.

**(b) The watchdog detects crash *loops*, not absence.** It's armed for "3 crashes in 300s". scout2 exited once, cleanly, and stayed exited — `RestartCount=0`, so it never registered as a loop. The manager logged zero errors in 30 days. A container that is simply *gone* is invisible to the current watchdog.

**(c) — found later — the watchdog was monitoring nothing at all.** Two independent defects made it a complete no-op in production:

- It filtered on `docker ps --filter name=ciris-agent-`. **No production container matches that pattern.** Real names are `ciris-datum`, `ciris-echo-core-jm2jy2`, `ciris-scout-remote-test-dahrb9`. Verified: the filter returns zero rows on every host. CLAUDE.md documented the wrong convention, and the code followed the doc.
- It ran against the **local** Docker socket. The manager runs on its own server, which hosts no agent containers.

So it logged `Crash loop watchdog started - threshold: 3 crashes in 300.0s` and then monitored an empty set forever. It would not have caught a crash loop either.

**Hardening:** add a liveness reconciler distinct from crash-loop detection — for every agent in the registry, assert a running container exists on its `server_id`, and alert/restart when it doesn't. That single check would have caught this in minutes rather than 3 weeks. It's also the check that makes host-reboot recovery automatic regardless of what you decide about restart policy.

---

## P1 — soak-run defects worth hardening before you add release load

### P1-1. Non-retryable auth failure retried forever at fixed cadence, no backoff.

Every running agent, continuously:

```
ERROR - ciris_adapters.ciris_accord_metrics.services - ❌ [default] FLUSH FAILED: N events:
        RuntimeError: CIRISLens API error 401: {"error":"verify_unknown_key"}
```

Volume over the retained window: scout1 2,952 tracebacks, echo-core 1,864, echo-speculative 2,000, in only 2.5–4 hours of log retention each. Cadence is three fixed-period flush schedules, ~3 attempts/minute, indefinitely:

```
21:56:29  21:56:33  21:57:00  21:57:29  21:57:33  21:58:00  ...
```

Interval never widens. A `401 verify_unknown_key` is a *permanent* auth/registration failure — the one class of error that should never be retried on a fixed short timer. Each failure emits a full multi-frame traceback, which is what's driving the incident log to rotate every few hours (see P1-5).

You've said the accord trace collector returns with the new-version migration. That's precisely why this matters now rather than later: **the migration window recreates this exact condition fleet-wide** — key not yet registered against the new backend, every agent hammering it at 3/min with full tracebacks while it comes up. Harden the client before the cutover, not after.

**Hardening:** classify 401/403 as non-retryable — stop the flush loop, log once at ERROR with a distinct stable string, and expose it as adapter state (`degraded: auth`) rather than as a per-attempt traceback. For genuinely retryable failures (5xx, timeouts), use exponential backoff with a cap and a circuit breaker. Log the *first* failure and *transitions*, not every attempt.

### P1-2. Orphaned scheduled task, failing every 60 s since June 6.

```
ERROR - persistence.models.thoughts - Failed to add thought thought_<ts>: FOREIGN KEY constraint failed
        sqlite3.IntegrityError: FOREIGN KEY constraint failed
ERROR - services.lifecycle.scheduler.service - Failed to trigger task task_1780753242.616828: task execution error
```

Exactly on the minute — 19:24:41, 19:25:41, 19:26:41 … The task id decodes to ~2026-06-06, the date of datum's last restart. A scheduled task is firing against a parent row that no longer exists; `add_thought` violates the FK; the scheduler swallows it and re-fires 60 s later. Observed 620 occurrences on echo-core in the retained window alone; extrapolated across ~8 weeks that's on the order of 80,000 failed inserts.

Two distinct defects: (a) scheduled tasks survive the deletion of the rows they depend on — no cascade, no validation at trigger time; (b) a task that fails deterministically is retried unboundedly with no dead-letter path.

**Hardening:** validate FK targets when the scheduler loads a task and drop/quarantine orphans at load; add a failure counter per scheduled task that moves it to a dead-letter state after N consecutive identical failures. Surface dead-lettered tasks in `status`.

### P1-3. Graceful shutdown livelocked for 7m53s. — ALREADY KNOWN, CLOSED as CIRISAgent#863

**Correction after filing:** this is not a new finding. CIRISAgent#863 ("SHUTDOWN
cognitive state handling has three compounding failure modes — agents stuck for
5–9 days") documents exactly this signature at much greater scale (round counters
of 512k–808k across all five agents) and is **closed**. The 471 iterations below
are the *tail* of that same incident, ending when datum was restarted on
2026-06-06. datum has run 7 weeks since with no recurrence. No issue was filed;
nothing further is needed here.

datum, 2026-06-06, 471 iterations at exactly 1 Hz:

```
13:31:24.947 ERROR - processors.states.shutdown_processor - Shutdown task disappeared!
13:31:25.954 ERROR - ... (×471, 1/sec)
13:39:17.569 ERROR - ...
```

Preceded by a single `CRITICAL [SIGNAL] SIGTERM received, requesting graceful shutdown`. The shutdown processor polls for a task that no longer exists, logs, sleeps 1s, repeats — with no bounded attempt count and no escape hatch. It only ended when the process was forcibly killed ~8 minutes in.

This is a release-critical path: canary deployment depends on `agent shutdown` completing cleanly, and the recent commit bumping the canary WAKEUP→WORK timeout 5→15 min suggests shutdown/startup timing is already marginal. An 8-minute livelock per agent will blow deployment windows.

**Hardening:** bound the shutdown poll (N attempts or a hard deadline), then escalate to forced shutdown and exit non-zero. Treat "shutdown task disappeared" as a terminal condition, not a retry condition — the task will not reappear.

### P1-4. CIRISVerify emits a false `SECURITY ALERT: Sources disagree - possible attack` every ~2.5 min.

scout1: 196 in ~4 h. Chain:

```
WARN  DNS DISAGREEMENT: US/doh-native rev=1 vs EU/doh-native   rev=0
WARN  DNS DISAGREEMENT: US/doh-native rev=1 vs EU/doh-bundled  rev=0
WARN  DNS DISAGREEMENT: US/doh-native rev=1 vs EU/json-api     rev=0
WARN  HTTPS: Failed to parse JSON response, url=https://api.registry.ciris-services-1.ai/v1/steward-key, error=error decoding response body
WARN  HTTPS unreachable — falling back to DNS-only consensus (degraded)
ERROR DNS sources disagree and HTTPS unreachable — cannot establish trusted consensus
ERROR SECURITY ALERT: Sources disagree - possible attack
```

Two independent root causes stacking:
1. **EU registry is stale at rev=0 while US is rev=1.** All 6 DNS lookups succeed (3/3 US, 3/3 EU) — the EU TXT record was simply never bumped. This matches the known EU-side gaps in `MIGRATION-cirispostgres-to-scoutdb.md` (no EU DNS wired, Hetzner DNS API not in IaC).
2. **The HTTPS tie-breaker is broken.** `api.registry.ciris-services-1.ai/v1/steward-key` returns a body the client can't decode. That endpoint exists precisely to resolve US/EU disagreement; with it down, a benign propagation lag is indistinguishable from an attack.

The security consequence isn't the alert — it's the desensitisation. A genuine key-substitution attack produces log lines identical to what's been printing every 2.5 minutes for weeks.

**Hardening:** bump the EU registry TXT to rev=1 and put it in IaC; fix or health-check the steward-key endpoint. In the client, distinguish *stale/lagging* (one source behind, monotonic revisions) from *conflicting* (divergent keys at the same revision) — only the latter is attack-shaped. Rate-limit the alert to first-occurrence-plus-transitions.

### P1-5. Log hygiene is destroying soak forensics.

- `Failed to convert node accord_metrics/events_total to ConfigNode: 'key'` — 3,623 on datum, 2,914 on scout1, ~2,000 on each echo. The config service cannot deserialise a node it wrote. Harmless-looking, enormous volume, every ~10 s.
- `[AUTH_STEP_INFO] discord: manifest exists=False` / `__file__=...` — pure debug breadcrumbs emitted at **WARNING**, 4 lines per adapter auth cycle, 1,208–2,430 occurrences per agent.
- Net effect: `incidents_latest.log` rotates at 2 MB roughly every 3–5 hours. **The retained incident history for echo-core at time of writing was 2.5 hours.** For an 11-week soak, that means essentially no incident forensics survive.

**Hardening:** demote `AUTH_STEP_INFO` to DEBUG; fix or demote the ConfigNode conversion warning; and either raise the incident-log retention or, better, make the incident log genuinely *incident*-only so it doesn't rotate on background noise. Right now the signal-to-noise ratio is such that the log is not usable for the purpose it exists for.

### P1-6. Manifest integrity check failing on datum.

14 occurrences of `verify_manifest_integrity: HASH MISMATCH!` with `check_full: manifest integrity verification FAILED` (ERROR), self-diagnosing as one of: registry uses a different hash algorithm (JSON hash vs concatenated values), file ordering differs, or the manifest was modified in transit. Correlates 1:1 with 14 Discord disconnect/reconnect events. Almost certainly the hash-algorithm mismatch rather than tampering, but it is currently indistinguishable from tampering — same category of desensitisation as P1-4, and worth resolving before release since it fires on every reconnect.

---

## P2 — the monitoring gap that let all of the above run silently

`ciris-manager-client status incidents` (shipped this week, commit `df2ed1c`) **reports every agent as clean against these logs.** I ran its classifier patterns against the real files:

```
llm_total_fail: 0   cb_open: 0    ponder_override: 0   speak_blocked: 0
secondary_err: 0    primary_err: 0    fragility: 0     sig_retry: 0
```

Zero across all four running agents, against logs containing thousands of ERROR lines. Since `verdict` is `"clean" if notable_total == 0`, and `status all` exits non-zero only "if anything notable", **the composite check currently exits 0 while scout2 is down, three agents are externally unreachable, and ~5,000 tracebacks/hour are being written.**

Concrete pattern bugs in `_INCIDENT_PATTERNS` (`ciris_manager_client/commands/status.py:47-63`):

- `("CIRISVerify", "verify_warn")` — the real logger name is `ciris_verify` (lowercase, underscore). Never matches.
- No pattern covers the highest-volume real errors: `FLUSH FAILED`, `FOREIGN KEY constraint failed`, `Shutdown task disappeared`, `SECURITY ALERT`, `HASH MISMATCH`.
- `_NOTABLE` therefore excludes every failure mode actually occurring in production.

Also note `_gather_incidents` greps `^{since_date}` against `incidents_latest.log` only — with rotation every few hours, "today" silently means "the last 2–5 hours."

**Hardening:** re-derive the pattern table from real production logs rather than from the expected-failure list, add the five signatures above, fix the `ciris_verify` case, glob rotated logs rather than `incidents_latest.log` alone, and add the two checks that would have caught the P0s — external endpoint probe and registry-vs-running-container reconciliation. Then add a regression test that asserts the classifier scores non-zero against a captured real log fixture, so it can't silently drift back to matching nothing.

---

## Cross-cutting patterns to harden against

Ranked by how many findings each one explains:

1. **Unbounded fixed-cadence retry on permanently-failing operations.** P1-1 (401), P1-2 (FK), P1-3 (shutdown poll). Same shape three times: no backoff, no attempt ceiling, no dead-letter, full traceback per attempt. This is the single highest-leverage fix — one retry/circuit-breaker utility applied at all three sites.
2. **Health signals that never traverse the real path.** P0-1 — every internal probe read green through a 46-day external outage because nothing tested the TLS path end to end. Health must be measured where the user sits.
3. **Detecting thrash but not absence.** P0-2 — the watchdog watches for too-many-restarts and is blind to zero-restarts-because-it's-gone. Reconcile desired state vs actual, don't just count crashes.
4. **Latent config that only fails on a long timer.** P0-1 again — `standalone` authenticator worked at provisioning and could not work at renewal, 90 days later. Anything that only exercises on a 90-day cycle needs to be tested on a short cycle (`certbot renew --dry-run` in CI/cron).
5. **Alert fatigue as a security regression.** P1-4, P1-6 — "possible attack" and "HASH MISMATCH" have both been continuous background noise for weeks. Distinguish lag from conflict; alert on transitions, not on every evaluation.

## Immediate sequence I'd suggest

1. Fix the `agents.ciris.ai` cert (webroot or DNS-01) — everything else, including CD notify, is blocked behind it.
2. Bring scout2's agent back up via `ciris-manager-client`, and decide `restart:` policy deliberately.
3. Land the retry/backoff hardening (P1-1) *before* the accord-collector migration, since the cutover reproduces the condition fleet-wide.
4. Fix the `status` classifier so the release soak is actually observable.
5. Bound the shutdown poll (P1-3) before relying on canary graceful shutdown.

---

*Data gathered read-only over SSH on 2026-07-30 ~22:00 UTC. Manager API was unavailable throughout (P0-1), so all figures come from container inspection and in-container logs rather than `ciris-manager-client status`.*
