# Salesforce AI backend — restart, autostart and watchdog

Everything here runs the **frozen** backend at
`../Salesforce_AI/Complete_Project`. Nothing in this folder edits that tree —
the port is passed through the environment, which `app/config.py` already
honours.

## The one command you need

```bash
sudo systemctl restart salesforce-app-restart.service
```

That stops anything stale, starts the backend on port 8010, brings the ngrok
tunnel up once the backend answers, and prints the public URL to the journal.

## Public URLs

| What | URL |
|---|---|
| **Download page** (share this) | `https://noninfluential-lamonica-unobservantly.ngrok-free.dev/download` |
| API base (for the Android app) | `https://noninfluential-lamonica-unobservantly.ngrok-free.dev` |
| Docs UI | `https://noninfluential-lamonica-unobservantly.ngrok-free.dev/docs` |
| Setup console | `https://noninfluential-lamonica-unobservantly.ngrok-free.dev/dashboard/` |

The tunnel points at **nginx on 127.0.0.1:8080**
(`/etc/nginx/sites-available/salesforce-public`), not at the backend directly,
so one domain serves both. nginx sends `/download/` from
`APK_and_Manual/` as static files and proxies everything else to the backend on
8010. Set `NGROK_TARGET_PORT="8010"` in `config.env` to bypass nginx and expose
the backend alone again.

Two nginx settings there are load-bearing: `client_max_body_size 512m` (the
1 MB default would reject meeting-audio uploads with a 413 the application never
sees) and `absolute_redirect off` (without it a bare `/download` redirects to
`http://<domain>:8080/...`, leaking the internal port and downgrading the
scheme).

The current URL is also written to `run/public_url.txt` after every start:

```bash
./restart_backend.sh url
```

> **This domain used to serve the learning-platform chatbot on port 8000.**
> A free ngrok plan includes exactly one domain, so publishing this backend
> meant taking it over. The chatbot still runs locally on `127.0.0.1:8000`; it
> simply has no public URL any more. To hand the domain back, set
> `NGROK_ENABLED="false"` in `config.env`, restart the service, and start the
> chatbot's tunnel again.

## Files

| File | What it is |
|---|---|
| `config.env` | All tunables — port, domain, timeouts. **Edit here, not in the scripts.** |
| `restart_backend.sh` | start / stop / restart / status / url / foreground |
| `healthcheck.sh` | Hourly probe; restarts the service when unreachable |
| `salesforce-app-restart.service` | The backend + tunnel unit |
| `salesforce-app-healthcheck.service` | Oneshot the timer fires |
| `salesforce-app-healthcheck.timer` | Fires hourly |
| `logs/` | `backend.log`, `ngrok.log` |
| `run/` | pidfiles, `public_url.txt` |

The three unit files are **copies**. The live ones are in
`/etc/systemd/system/`. After editing a unit here:

```bash
sudo cp salesforce-app-*.service salesforce-app-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart salesforce-app-restart.service
```

Editing `config.env` or the `.sh` files needs no copy — the units point at
this folder directly.

## Manual use, without systemd

```bash
./restart_backend.sh start     # idempotent
./restart_backend.sh stop
./restart_backend.sh restart
./restart_backend.sh status    # what is up, and on which URL
./restart_backend.sh url       # public URL only
```

## Autostart after a reboot

Both units are enabled:

```
/etc/systemd/system/multi-user.target.wants/salesforce-app-restart.service
/etc/systemd/system/timers.target.wants/salesforce-app-healthcheck.timer
```

The backend comes up after `network-online.target`. The first health probe
runs 10 minutes after boot, then hourly.

## The watchdog

`salesforce-app-healthcheck.timer` fires `healthcheck.sh` every hour
(`OnUnitActiveSec=1h`, first run `OnBootSec=10min`, `Persistent=true` so a run
missed while the VM was off happens shortly after it returns).

Two probes:

1. `http://127.0.0.1:8010/health` — is the backend alive?
2. `https://<ngrok domain>/health` — is the tunnel carrying traffic?

Local is checked first so the log names the real fault instead of blaming the
tunnel for a dead backend. The public probe is retried **3 times with 10s
gaps** — one timeout across the internet is not proof of an outage, and a
needless restart drops in-flight work and re-warms the Whisper model. Either
probe failing for good triggers:

```bash
systemctl restart salesforce-app-restart.service
```

The healthcheck unit runs as **root**, because calling `systemctl restart` is
its entire job. It only ever runs `curl` and `systemctl`.

## Watching it

```bash
sudo systemctl status salesforce-app-restart.service
sudo journalctl -u salesforce-app-restart.service -f
sudo journalctl -u salesforce-app-healthcheck.service --since today
sudo systemctl list-timers salesforce-app-healthcheck.timer
tail -f logs/backend.log logs/ngrok.log
```

## Design notes

**Why `Type=exec` and not a background-and-return script.** The script's last
act is `exec`ing uvicorn, so the real server is the unit's `MAINPID`. systemd
then supervises the actual process: `Restart=on-failure` works (verified — a
`kill -9` is recovered in ~20s), and `systemctl stop` tears down the whole
control group including ngrok. A script that backgrounds both processes and
returns would need `KillMode=none`, which systemd now warns is deprecated and
which leaves systemd with nothing to watch.

**Why the tunnel starts in a child.** ngrok must not publish the domain before
the backend can answer, or the first caller through it gets a 502. A child
process waits for `/health`, then raises the tunnel. It stays inside the
service cgroup, so systemd still cleans it up.

**Why processes are matched by cwd, not by command line.** `stop` finds
whatever listens on port 8010 and confirms `/proc/<pid>/cwd` is the backend
directory before killing it. The server can be launched as
`./.venv/bin/python run.py` or with an absolute path, and a `pgrep` pattern
written for one silently misses the other — leaving a stale server on the port
while the script reports success. Matching the cwd also guarantees another
project's process is never killed for sitting on that port.

**`HOME` is set explicitly** in the unit. systemd does not set it for a
`User=` service, and without it ngrok cannot find its authtoken
(`~/.config/ngrok/ngrok.yml`) and Whisper re-downloads its 3 GB model into a
different cache on every boot.

## Ports

| Port | Owner |
|---|---|
| 8000 | `yuvipep_learning_platform_chatbot` — **not managed here** |
| 8010 | this backend |
| 4040 | ngrok inspection UI (`http://127.0.0.1:4040`) |

The backend is on 8010 because 8000 was already taken. If you free 8000 and
want it back, change `PORT` in `config.env` and restart. Note the Android app's
`EMULATOR_BASE_URL` is hardcoded to `10.0.2.2:8000`, though it can be
overridden at runtime from the app's environment sheet.
