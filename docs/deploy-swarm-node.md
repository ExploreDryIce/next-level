# Deploying the swarm node reader fix (plan, not yet executed)

Branch `agents/node-reader`. Nothing here has been run. Each step names the
machine it runs on. Never print the broker token; every command below reads it
from the environment or a prompt.

## What changes

| Piece | Files | Effect |
|---|---|---|
| Node | `src/node/network.py`, `src/node/swarm_node.py` (copy `config.py` and `__init__.py` with them so the set matches one commit) | Reads its socket continuously; one connection per process; reconnects with backoff (5 s doubling to 300 s); heartbeat every min(gossip, 60) s; `--log-file` / `DVCE_NODE_LOG_FILE` rotating log (10 MB x 5, stderr then carries warnings only). |
| Broker | `src/swarm/broker.py` | Per-node bounded outbound queue (1000 msgs / 8 MiB). A node that stops reading loses relays (counted as `messages_dropped` / `patterns_dropped` in `status`) instead of stalling the pusher and everyone behind it. |

Protocol is unchanged, so old nodes work with the new broker and new nodes with
the old broker. Order does not matter; the plan does the nodes first (no broker
restart needed for them), then the broker.

**Token gotcha.** Since 8003899 the node has no token fallback: it reads
`DVCE_BROKER_TOKEN` from its environment and raises `KeyError` if it is unset.
The June copy on TerrorNode (and possibly TowerSeven) may still be
authenticating with the old built-in default, which the broker accepts only as a
legacy token (the broker log shows `'terrornode' authenticated with a LEGACY
token` and the same for `towerseven`). Each node must have the current token in
its service environment before the new code starts, or it will crash-loop.

## 0. Before any machine (Mac, owner)

1. Review and merge `agents/node-reader` into `main` of next-level; push. Note
   the merge commit: `git -C /Users/webber/Desktop/next-level rev-parse --short HEAD`
   (called `$REV` below).
2. Baseline, so the fix can be measured:
   ```bash
   LOG=~/.dvce/logs/broker.error.log
   for n in terrornode towerseven macbook-m4; do
     echo "$n registrations=$(grep -c "Registered: $n " $LOG) collisions=$(grep -c "collision: '$n'" $LOG)"
   done
   ```

## 1. TerrorNode (Windows, `ssh jwebb@100.99.237.66`, PowerShell)

Code at `E:\next-level` is a plain copy (not a git checkout). The scheduled task
`DVCE-SwarmNode` runs it through a `cmd` wrapper; since 2026-10-15 it has
RestartCount 999 / PT1M and a 5-minute keepalive trigger
(MultipleInstances=IgnoreNew), so it must be **disabled**, not just stopped,
while files are replaced.

1. Record what the task runs and back it up:
   ```powershell
   $stamp = '20261015'
   $bk = "E:\dvce-backups\swarm-node-$stamp"; New-Item -ItemType Directory -Force $bk | Out-Null
   Export-ScheduledTask -TaskName DVCE-SwarmNode | Out-File "$bk\DVCE-SwarmNode.xml" -Encoding utf8
   (Get-ScheduledTask DVCE-SwarmNode).Actions | Format-List Execute, Arguments, WorkingDirectory
   ```
   If the action is a `.bat`, copy it into `$bk` too. Check it does not contain
   the token in clear; if it does, that is a separate finding (move it out, rotate).
2. Make sure the token is in the environment the task will get (user scope for
   `jwebb`, or machine scope if the task runs as SYSTEM). Check without printing it:
   ```powershell
   foreach ($s in 'User','Machine') { "$s: " + [bool][Environment]::GetEnvironmentVariable('DVCE_BROKER_TOKEN', $s) }
   ```
   If neither is `True`, set it from a prompt (value comes from the Mac's
   `~/.dvce/secrets.env` / broker plist; do not paste it into a command line):
   ```powershell
   $t = Read-Host 'DVCE broker token' -AsSecureString
   [Environment]::SetEnvironmentVariable('DVCE_BROKER_TOKEN', [Net.NetworkCredential]::new('', $t).Password, 'User')
   ```
3. Stop the node and keep it stopped:
   ```powershell
   Disable-ScheduledTask DVCE-SwarmNode; Stop-ScheduledTask DVCE-SwarmNode
   Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
     Where-Object CommandLine -match 'swarm_node' | Select-Object ProcessId, CommandLine
   # If one is still listed: Stop-Process -Id <pid>
   ```
4. Back up the node code: `Copy-Item E:\next-level\src\node "$bk\node" -Recurse`
5. Copy the new files (on the **Mac**):
   ```bash
   cd /Users/webber/Desktop/next-level/src/node
   scp network.py swarm_node.py config.py __init__.py "jwebb@100.99.237.66:E:/next-level/src/node/"
   ssh jwebb@100.99.237.66 "echo next-level $REV > E:\next-level\src\node\DEPLOYED_FROM.txt"
   ```
   (Windows OpenSSH also accepts `/E:/next-level/src/node/` if the first form is refused.)
6. Turn on the log file. In the task's `.bat` (or the action arguments) add
   `--log-file E:\dvce-data\logs\swarm_node.log` to the `python ... swarm_node.py`
   command; or set `DVCE_NODE_LOG_FILE` the same way as the token. Keep any
   existing `--profile terrornode` / `--config` argument as it is.
7. Smoke-test once in the foreground (Ctrl+C after two status lines):
   ```powershell
   cd E:\next-level\src\node; python swarm_node.py --profile terrornode
   ```
   Expect `Registered! Swarm size: N`, then `[terrornode] ... registrations=1`.
   `KeyError: 'DVCE_BROKER_TOKEN'` = step 2 not effective in this shell;
   `Broker rejected registration: invalid token` = wrong token.
8. Start the service: `Enable-ScheduledTask DVCE-SwarmNode; Start-ScheduledTask DVCE-SwarmNode`

### Verify (30-60 min)
- TerrorNode: `Get-Content E:\dvce-data\logs\swarm_node.log -Tail 20` shows one
  `Registered!`, status lines every minute with `registrations=1` and
  `broker_msgs` rising when the broker relays.
- Mac broker log: exactly one new `Registered: terrornode` since the start, no
  `collision: 'terrornode'`, no `Dropping silent node: terrornode`, no `Reaped
  stale node: terrornode`:
  ```bash
  grep -E "100\.99\.237\.66|terrornode" ~/.dvce/logs/broker.error.log | tail -20
  ```
- Broker status from the Mac (loopback, no token needed):
  ```bash
  printf '{"type":"status"}\n' | nc -w 2 127.0.0.1 9876 | python3 -c \
    'import json,sys; [print(n["node_id"], n["last_heartbeat_ago"], n.get("messages_dropped")) for n in json.load(sys.stdin)["nodes"]]'
  ```
  `terrornode` with `last_heartbeat_ago` < 90.

### Rollback
```powershell
Disable-ScheduledTask DVCE-SwarmNode; Stop-ScheduledTask DVCE-SwarmNode
Remove-Item E:\next-level\src\node -Recurse -Force
Copy-Item "$bk\node" E:\next-level\src\node -Recurse
# restore the .bat from $bk if it was edited
Enable-ScheduledTask DVCE-SwarmNode; Start-ScheduledTask DVCE-SwarmNode
```
(The task XML backup can be re-imported with `Register-ScheduledTask -Xml (Get-Content "$bk\DVCE-SwarmNode.xml" -Raw) -TaskName DVCE-SwarmNode -Force`.)

## 2. TowerSeven (Raspberry Pi 3, `ssh webber@100.122.21.64`)

Two node processes run today: one from an `@reboot` crontab line running
`swarm_node.py`, one from `dvce-swarm.service` running `node.py`. The broker
sees `towerseven` registering as `domain=grid` (the stock `towerseven` profile
says `natural`), so whichever process uses that identity has its own config.
`towerseven-comms` is a separate pusher; leave it alone.

1. Inventory (read only):
   ```bash
   crontab -l
   systemctl cat dvce-swarm.service
   systemctl show -p MainPID,ExecStart dvce-swarm.service
   ps -eo pid,ppid,args | grep -E 'swarm_node|node\.py' | grep -v grep
   ```
   Find out what `node.py` is. **Owner decision** if it is not next-level's
   node (for example a separate script that does not import `network.py`):
   this fix only reaches it if the service is pointed at
   `.../next-level/src/node/swarm_node.py` with the same node_id/domain (a
   `--config` JSON written from the running config). Also note `python3 --version`
   (the node code parses on 3.8+).
2. Back up:
   ```bash
   S=20261015; B=~/dvce-backups/swarm-node-$S; mkdir -p $B
   crontab -l > $B/crontab
   sudo cp /etc/systemd/system/dvce-swarm.service $B/  # and any drop-ins under dvce-swarm.service.d/
   cp -a <next-level dir>/src/node $B/node
   ```
3. Remove the duplicate cron node and stop it:
   ```bash
   crontab -l | grep -n swarm_node.py                  # confirm it is only that one line
   crontab -l | grep -v 'swarm_node.py' | crontab -
   kill <pid of the cron-started swarm_node.py>        # NOT the service MainPID
   ```
4. Copy the files (on the **Mac**):
   `scp src/node/{network.py,swarm_node.py,config.py,__init__.py} webber@100.122.21.64:<next-level dir>/src/node/`
5. Service settings via a drop-in (`sudo systemctl edit dvce-swarm.service`):
   ```ini
   [Service]
   EnvironmentFile=/etc/dvce/swarm.env       # holds DVCE_BROKER_TOKEN=..., mode 600, owner root
   Environment=DVCE_NODE_LOG_FILE=/home/webber/dvce-logs/swarm_node.log
   Restart=always
   RestartSec=10
   ```
   Skip `EnvironmentFile` if the unit already provides the token (check with
   `sudo systemctl show dvce-swarm.service -p Environment,EnvironmentFiles` and
   look only at the variable names). Then
   `sudo systemctl daemon-reload && sudo systemctl restart dvce-swarm.service`.

### Verify
- `systemctl status dvce-swarm.service` active; `ps` shows exactly one node process.
- `tail -20 ~/dvce-logs/swarm_node.log`: one `Registered!`, `registrations=1`.
  Heartbeats are now every 60 s (gossip was 300 s, equal to the broker's
  300 s stale limit, which is why `Reaped stale node: towerseven` appears in
  the broker log).
- Mac: `grep -E "100\.122\.21\.64|towerseven" ~/.dvce/logs/broker.error.log | grep -v comms | tail`
  shows one registration, no collision, no reaping.
- Reboot test when convenient (`sudo reboot`): after boot still one process.

### Rollback
```bash
crontab $B/crontab
sudo rm -rf /etc/systemd/system/dvce-swarm.service.d && sudo cp $B/dvce-swarm.service /etc/systemd/system/
rm -rf <next-level dir>/src/node && cp -a $B/node <next-level dir>/src/node
sudo systemctl daemon-reload && sudo systemctl restart dvce-swarm.service
```

## 3. Mac node (`com.dvce.node`) and broker (`com.dvce.broker`)

Both run straight from the main checkout `/Users/webber/Desktop/next-level`, so
the merge in step 0 is the copy.

1. Back up the plists: `cp ~/Library/LaunchAgents/com.dvce.{node,broker}.plist ~/.dvce/backups/`
2. Optional, for rotation: add `DVCE_NODE_LOG_FILE` = `/Users/webber/.dvce/logs/swarm_node.log`
   under `EnvironmentVariables` in `com.dvce.node.plist` (then `node.error.log`,
   18 MB and unrotated today, only receives warnings). Reload with
   `launchctl bootout gui/$(id -u)/com.dvce.node && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dvce.node.plist`.
3. Restart the node: `launchctl kickstart -k gui/$(id -u)/com.dvce.node`
4. Restart the broker (all nodes drop once and re-register within seconds;
   finnhub/streamlit pushers simply reconnect on their next push):
   `launchctl kickstart -k gui/$(id -u)/com.dvce.broker`

### Verify
- The status command above lists every node with `messages_dropped`; after the
  remote nodes are updated their `messages_dropped` stays 0. A node that still
  shows a growing `messages_dropped` is still not reading (old code).
- Rerun the step-0 baseline after a few hours: each node's registration count
  rises by one per restart, not every few minutes.
- `grep "not keeping up" ~/.dvce/logs/broker.error.log` names any node that
  still falls behind.

### Rollback
`git -C /Users/webber/Desktop/next-level revert -m 1 <merge commit>`, then the
two `kickstart -k` commands above; restore the plists from `~/.dvce/backups/`
if they were edited.

## Known gaps left open

- Until TerrorNode's node log exists, the exact trigger of its 2-4 minute
  re-registration cycle on the June code is inferred, not observed (see the
  branch's report). If the new node still re-registers, its log now says why
  (`Connection to broker lost: ...` / `Send failed: ...`).
- Mass "Reaped stale node" bursts covering every node at once (e.g. 08:54:05
  on 2026-10-15) look like the Mac sleeping, not a node problem.
- `_send_sms_alert` runs SMTP synchronously on the broker loop when an
  unknown node_id registers; it can freeze the broker for the SMTP timeout.
