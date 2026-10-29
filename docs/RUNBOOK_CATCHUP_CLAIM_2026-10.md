# Runbook: one-time catch-up claim of the legacy-admin agents (2026-10)

**Status:** executing. Tick each step as it lands; the rollback for a step is
valid only until the next step starts. One agent at a time; the canary is
`echo-speculative-4fc6ru`.

## Why

The five managed agents (datum, echo-core-jm2jy2, echo-speculative-4fc6ru,
scout-remote-test-dahrb9 on scout1 and scout2) run ciris-agent 2.9.38 and are
owned only by the legacy `admin` ROOT. None has a fed-ID owner-binding. The
goal is: every agent on 2.16.5 (ciris-server 0.5.235) with **owner = Eric's
fed-ID** `eric-moore-v2-portable-f34de31d8c21-6e2b4kpvxk`, with the manager's
client node holding a roster key of that fed-ID so future owner acts can be
signed from the laptop.

This is a manual, one-time migration. It uses the staged owner-binding path
(CIRISServer#811/#813, 0.5.234+): the owner's device signs, the agent applies.
No new network door was built for it.

## Roles

| Where | What it holds | What it does |
|---|---|---|
| **Client** – Eric's laptop, `~/ciris-manager-node` (ciris-server 0.5.235, TPM tier) + `ciris-manager-client` | roster key `<fedID>-<fp>` (TPM-sealed), own node key | associate, self-claim, `sign-owner-binding` |
| **Manager** – 45.76.226.222 | manager code, Docker TLS certs, registry; **no owner key** | upgrade, `/app/identity` persistence, admin password reset, apply the staged binding |
| **Agents** – main/scout1/scout2 | their own node identity under `/app/identity` | accept `upgrade-owner` under the admin session |

The fed-ID keyset's only copy is the retired QA home. It is **read in place or
staged in RAM only** (`/dev/shm`, shredded right after) and never copied to disk
or to any other host. Tell the bridge session before and after any staging.

## Preconditions (all met 2026-10-28 unless noted)

- [x] CIRISManager #29 (persist `/app/identity`) merged and deployed (run 40702047590 ✅).
- [x] CIRISManager #30 (admin password reset) deployed (run 40702072199 ✅, manager at 1aa01a8 since 14:16Z).
- [x] CIRISAgent 2.16.5-stable published, pins ciris-server 0.5.235. Deployment `c5ca18f0` staged, pending.
- [x] ciris-server 0.5.235 on PyPI; client node venv to be moved to it (step 1).
- [x] scout2 TLS cert fixed 2026-10-27 (was expired; copied from scout1, valid to 2026-12-28).
- [x] `ciris-manager-client auth login` done by Eric.
- [x] Nothing has rolled: all five agents still on 2.9.38, all deployments pending.

## Progress log

| When (UTC) | Step | Agent | Result |
|---|---|---|---|
| 10-28 14:16 | 1 | client | fresh home, 0.5.235, TPM tier (5 plugin selections, 0 software), node key `ciris-server-qxwxvyeclu` |
| 10-28 14:17 | 2 | client | associate **200 held:false**, roster key `…-6e2b4kpvxk-c364z6olxz`, custody tpm; staging shredded |
| 10-28 14:18 | 3 | client | self-claim 200; binding `9af61113` = `…-c364z6olxz → ciris-server-qxwxvyeclu`; owner = fedID |
| 10-28 14:20 | 5 | echo-speculative | deployment `f347bf47` → 2.16.5; `/app/identity` migrated (Aug-26 actor keys + new `ciris-node-bootstrap-2qyumdzwnl`); held unowned |
| 10-28 14:31 | 6 | echo-speculative | ROOT `wa-2025-11-25-A382B3` reset; backup `…-default-main-20261028T143132Z.json` |
| 10-28 14:33 | 7 | echo-speculative | staged binding signed, roster proof present |
| 10-28 14:34 | 8 | echo-speculative | upgrade-owner **200 staged:true**, binding `fd9c922e`; owned-nodes.owner = fedID; agent left the hold → WAKEUP, health 200 |
| 10-28 15:05 | – | canary | reached **WORK** on 2.16.5; primary (OpenRouter) healthy, Groq secondary failing (see hold below) |
| 10-28 15:10 | hold | datum, echo-core, scout1, scout2 | **HELD on 2.9.38 by Eric's ruling**: the Groq qwen3.6 `reasoning_effort` fix (CIRISAgent PR #1327) rides **2.17.0**, no 2.16.x hotfix. Resume steps 5–8 with `--version 2.17.0-stable` once it ships. echo-speculative stays on 2.16.5. |
| 10-29 18:30 | check | all five | 2.17.0-stable published, staged by CD for review (not started). All five running; scouts have 9-10 GB free for a 2 GB image. Manager client token expired: sign in before step 5. Traces: none reach the canonical since 2026-09-24 (owner consent missing, see step 5) |

### Gotchas met (fold into the next run)
- `ciris-manager-client agent get/list` reported the stopped canary as `running` for >37 s (CIRISManager#33). Gate step 6 on the container state read from the agent's host, not on `agent get`.
- The reset script prints the password **bare on its own line** after the `^ SAVE THIS PASSWORD` marker; capture the whole output to a 0600 file.
- Remote Docker from the manager host is `--host tcp://<vpc_ip>:2376` (not `https://`), certs in `/etc/ciris-manager/docker-certs/agents|scout1|scout2`.
- The SSE `deployment watch` drops through Cloudflare; poll `deployment status` / `agent list`.
- The watchdog raised a false "crash loop" on the operator stop (CIRISManager#32). Ignore that CRITICAL during step 6; it does not restart anything.
- The agent re-reads ownership on a tick; no restart is needed after step 8.

### Bugs found and filed
- CIRISPersist#1139 — `nodes_stewarded_by` misses roster-key-signed bindings, lists the roster key as a node (owned-nodes wrong on client and agent).
- CIRISServer#829 — claim-remote / upgrade-owner echo the signer as `owner`.
- CIRISManager#32 (watchdog false crash loop + wrong Docker client on stop), #33 (stale agent status after stop).
- Agent: Groq secondary rejects `reasoning_effort` on 2.16.5 (sent to the agent session); `delete_task` FOREIGN KEY errors cleaning stale WAKEUP tasks.
- Design question to the server session: the agent holds an unsigned `(fedID → node key)` content-occurrence row; a node must not read as a member of the owner's self.

## Step 0 – Baseline (read-only)

Record, per agent: `ciris-manager-client --format json agent get <id>` (global
`--format` goes before the subcommand). On 2.9.38 the node's `/v1/identity` is
not proxied through 8080, so the pre-upgrade node key is not readable; the key
changes on the 2.16 boot anyway - record it in step 5. Keep the
output in the manager host's `/root/catchup-claim-2026-10/baseline/`.

Rollback: none needed.

## Step 1 – Client node: fresh home on 0.5.235

The current `~/ciris-manager-node/home` carries a stale pre-#805 occurrence
(`…-device-fd52c970d9ee`, unsigned, local only) that made the roster count two
keys and hold the last associate as a proposal. Start clean.

1. Stop the node. Move `home` to `home.retired-<date>`; shred its key files
   (`identity/user/*`, `identity/keys/*`); keep `data/` for reference, 0700.
2. `pip install --no-cache-dir ciris-server==0.5.235` in the venv.
3. Start: `CIRIS_HOME=$N/home CIRIS_TPM_PLUGIN=<plugin.so> ciris-server --home $N/home`.
4. Check: `GET /v1/setup/status` → `is_first_run: true`; log shows
   `Using ciris-tpm-plugin` storage for the node signers.

Rollback: stop; move `home.retired-<date>` back. Nothing left this laptop.

## Step 2 – Client node: join the self roster (associate)

`POST /v1/self/associate {key_id: <fedID>, seed_dir: <RAM staging>, classical: software, pqc: tpm, device: tpm}`.

Expected **200** `{held: false, associated_key_id: <fedID>-<fp>, device_custody: tpm}`.
From a clean home the roster is the fed-ID alone, so the add lands and
replicates (signed by the fed-ID). A **202 held** means the roster already
counts ≥2 keys: stop and find out which; do not approve from the same node.

Checks: `federation_identity_occurrences` has one signed row
`(<fedID>, <fedID>-<fp>)`; `identity/user/active_user_alias` = `<fedID>`;
staging dir gone. Report to the bridge.

Rollback: stop the node, shred `home/identity/user/*` and `home/identity/keys/*`.
The roster row has replicated; its reversal is a revoke from an owned device
(`POST /v1/self/occurrence/revoke`), which Eric does if the key is unwanted.

## Step 3 – Client node: self-claim (bind its node key to Eric)

On first run, loopback: `POST /v1/setup/claim-remote {node_code: <own node-code>,
claim_pin: <home/claim_pin>, cohort_scope: self, target_url: http://127.0.0.1:4243,
owner_username: eric, owner_password: <generated, kept in Eric's secret store>}`.

Expected 200, `identity_key_id` = the fed-ID (the roster key signs; #806 proof
resolves it). Checks: `GET /v1/setup/owned-nodes` → owner = fed-ID, nodes = [own
node key]; `POST /v1/auth/login {username, password}` returns a SYSTEM_ADMIN
session.

Rollback: `POST /v1/self/nodes/<own node key>/release` as owner (or redo step 1).
This node is a client; releasing it costs nothing in prod.

## Step 4 – Manager: deploy #30, verify

Wait for run 40702072199 ✅. On the manager host:
`cd /opt/ciris-manager && git log -1` shows `1aa01a8`;
`ls ciris_manager/identity_volume.py ciris_manager/admin_password_reset.py`;
`systemctl is-active ciris-manager`; API answers within ~4 min.

Rollback: `git revert` on main (auto-deploys), or on the host
`git reset --hard 8c524c3 && systemctl restart ciris-manager`.

## Step 5 – Per agent: upgrade to 2.16.5 (canary first)

> **Hold (2026-10-28, Eric):** 2.16.5 sends `reasoning_effort: "low"` to the Groq
> qwen3.6-27b secondary, which Groq rejects (enum `none|default`), so every
> secondary call fails. All five agents use that secondary. The fix (CIRISAgent
> PR #1327) ships in **2.17.0**; there is no 2.16.x hotfix. The remaining four
> agents stay on 2.9.38 until 2.17.0 is released, then run this step with
> `--version 2.17.0-stable`. The canary keeps running on 2.16.5 on its primary.
>
> **2.17.0 is out (2026-10-29)** and carries the Groq fix. Use
> `--version 2.17.0-stable` for all five agents, the canary included. Do not
> start the CD-staged 2.17.0 canary deployment (it targets `:latest` across
> all five); cancel it with the rest in step 9.
>
> **Traces do not reach the canonical, and 2.17.0 alone does not change that.**
> The canonical holds no echo-speculative or echo-core trace since 2026-09-24,
> the day those agents were recreated on 2.9.38, and refused none: the
> batches seal locally and never ship. Shipping needs an owner-authored
> `consent:community_trust` grant naming the node, the owner and the agent
> key. On 2.17.0 (server 0.5.241) the agent asks for the owner's pen, finds
> none on the host, and logs "community-trust grant DEFERRED". That is
> expected after this upgrade and is not an abort criterion. Fixing it is a
> separate owner act per agent: `ciris-manager-client`, which holds the
> owner's user key, signs the consent grants for the owner and the manager
> applies them inside each agent, the same shape as steps 7 and 8. No owner
> key goes onto an agent host. Both doors belong to CIRISServer and do not
> exist yet (0.5.241). They follow `sign-owner-binding` and `upgrade-owner`:
> the client node signs `consent:community_trust:v1` (about the target node,
> subjects node, owner and agent, federation scope) plus `consent:replication:v1`;
> the agent's node verifies each row is signed by its owner and about itself,
> then stores it. CIRISAgent treats an applied owner grant as the crossing.
>
> Before consent matters the agent needs a canonical to deliver to: on
> echo-speculative the node lists no canonical peer and its delivery probe
> never runs. Its boot log shows persist's genesis step refusing the baked
> canonical seed (`ciris-canonical-1-d7bdeu223k`, `re_scrub`, "over the
> existing anchor-scrubbed row"). Raised with the server side.

`ciris-manager-client agent deploy <id> --version 2.16.5-stable --strategy docker
[--server-id scout1|scout2] [--occurrence-id 002]`. Cancel the other staged
canary deployments afterwards so none fires on its own.

What #29 does on the recreate: moves the old container's `/app/identity` to
`/opt/ciris/agents/<id>/identity` (0700, 1000:1000) and adds the bind. On the
first 2.16 boot the node re-keys to `ciris-node-bootstrap-*`; the old key becomes
the actor. The agent will log **"OWNED BUT UNBOUND" (legacy_root)** and hold
until step 8. That is expected.

Checks: container running on 2.16.5; `/app/identity` bind present
(`agent get` → mounts); `GET /v1/identity` → new `node_key_id` (record it);
`GET /v1/setup/status` → `is_first_run: false`.

Rollback: `ciris-manager-client agent deploy <id> --version 2.9.38-stable
--strategy docker`. The 2.9.38 image is retained (see
`docs/ROLLBACK_AND_IMAGE_RETENTION.md`). The identity bind stays; 2.9.38 reads
it fine (verified 2026-10-22 on `claimtest-f`: same-version recreate kept the
key, files byte-identical). If the migration itself fails, #29 restarts the old
container and refuses the recreate - nothing to roll back.

## Step 6 – Per agent: admin password reset (manager console)

On the manager host, agent stopped:
```
ciris-manager-client agent stop <id> [--server-id …] [--occurrence-id …]
./venv/bin/python scripts/reset_agent_passwords.py <id> [--server-id …]            # dry run
./venv/bin/python scripts/reset_agent_passwords.py <id> [--server-id …] --apply
ciris-manager-client agent start <id> …
```
Dry run first and read the row it names. `--apply` prints the password once;
put it in Eric's secret store, not the registry. The previous hash is saved to
`/opt/ciris/agents/password-reset-backups/<agent>-<stamp>.json` (0600).

Rollback: restore the saved hash into `cirislens_wa_cert` (the script's backup
has the row), or simply reset again. Either way the agent must be stopped.

## Step 7 – Client: sign the staged binding

On the laptop, with the owner session from step 3:
`POST http://127.0.0.1:4243/v1/setup/sign-owner-binding {node_key_id: <agent's new node key>, cohort_scope: self}`
→ `{node_key_id, cohort_scope, owner_binding, owner_roster_proof}`. Save as
`staged-<agent>.json`. It is signed data only; it can travel to the manager host
over ssh. Sign one per agent; the target refuses a binding for any other key.

Rollback: a staged file applied nowhere binds nothing; delete it.

## Step 8 – Per agent: apply (manager console → agent loopback)

Through the agent's server Docker API from the manager host:
```
docker --host https://<vpc_ip>:2376 --tlsverify --tlscacert … --tlscert … --tlskey … \
  exec <container> sh -c 'TOKEN=$(curl -s -X POST http://127.0.0.1:4243/v1/auth/login \
    -H content-type:application/json -d "{\"username\":\"admin\",\"password\":\"<step 6>\"}" | <extract token>); \
  curl -s -X POST http://127.0.0.1:4243/v1/self/upgrade-owner \
    -H "authorization: Bearer $TOKEN" -H content-type:application/json -d @-' < staged-<agent>.json
```
Expected 200 `{owner: <fedID>, node_key_id, owner_binding_attestation_id, staged: true}`.
Refusals: 409 `upgrade_owner.already_owned` (stop, investigate); 400
`upgrade_owner.binding_rejected` (wrong node key - re-check step 7's input;
nothing was written).

Checks: `GET /v1/setup/owned-nodes` → owner = fed-ID; agent leaves the
"unowned" hold and reaches WORK (`ciris-manager-client agent list`); no
"OWNED BUT UNBOUND" on the next boot. **Canary soak**: leave
echo-speculative-4fc6ru 24 h before the other four (moot while the 2.17.0
hold above is in force; the soak is already running).

Rollback: the binding is a signed, replicated owner fact. Its reversal is the
owner releasing the node (`POST /v1/self/nodes/<node key>/release`, from the
client with the owner session), after which the agent returns to the legacy-ROOT
hold. A rollback of the *version* (step 5's rollback) does not undo the binding.

## Step 9 – Close out

- Cancel every remaining staged 2.16.x deployment (`deployment cancel … --reason "Superseded"`).
- Confirm the canonical shows the five owner-bindings and the client's roster key (bridge session).
- Delete `staged-*.json` from the manager host; keep the baseline.
- Remove the local scratch fixtures (`claimtest-f` and its volumes).
- Update `project_long_soak_fleet` memory: fixtures are now 2.16.5, owned by the fed-ID.

## Abort criteria

Stop and report rather than continue if: associate answers 202; the self-claim
records any owner other than the fed-ID; the canary does not reach WORK within
15 min of step 8; any step's rollback is exercised; the bridge reports the
keyset copied anywhere.
