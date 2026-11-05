#!/usr/bin/env bash
#
# Start / stop / restart the YuviPep Salesforce AI backend and its ngrok tunnel.
#
#   ./restart_backend.sh start     launch backend + tunnel (idempotent)
#   ./restart_backend.sh stop      stop both
#   ./restart_backend.sh restart   stop then start
#   ./restart_backend.sh status    what is running, and on which URL
#   ./restart_backend.sh url       print the public URL only (script-friendly)
#   ./restart_backend.sh foreground  used by systemd; see below
#
# `foreground` is what the systemd unit calls. It clears any stale processes,
# arranges for the tunnel to come up once the backend answers, then *execs*
# uvicorn so the server becomes the service's main process. That is what lets
# systemd supervise it honestly: MAINPID is the real server, `Restart=` works,
# and stopping the unit tears down the whole control group — ngrok included.
# The alternative (backgrounding both and returning) needs the deprecated
# KillMode=none and leaves systemd with nothing to watch.
#
# Normally driven by systemd:
#   sudo systemctl restart salesforce-app-restart.service
#
# The backend tree itself is FROZEN. Nothing here edits it — the port is passed
# in the environment, which app/config.py already honours.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.env"

RUN_DIR="${SCRIPT_DIR}/run"
LOG_DIR="${SCRIPT_DIR}/logs"
BACKEND_PIDFILE="${RUN_DIR}/backend.pid"
NGROK_PIDFILE="${RUN_DIR}/ngrok.pid"
URL_FILE="${RUN_DIR}/public_url.txt"
BACKEND_LOG="${LOG_DIR}/backend.log"
NGROK_LOG="${LOG_DIR}/ngrok.log"

PYTHON="${APP_DIR}/.venv/bin/python"
LOCAL_HEALTH="http://127.0.0.1:${PORT}${HEALTH_PATH}"
# Falls back to the backend port, so a config.env predating this key
# still behaves exactly as it used to.
NGROK_TARGET_PORT="${NGROK_TARGET_PORT:-$PORT}"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# ── helpers ──────────────────────────────────────────────────────────────────

# Is the pid in $1's pidfile alive?
pid_alive() {
    local pidfile="$1" pid
    [[ -f "${pidfile}" ]] || return 1
    pid="$(cat "${pidfile}" 2>/dev/null)"
    [[ -n "${pid}" ]] || return 1
    kill -0 "${pid}" 2>/dev/null
}

# Terminate a pid politely, then firmly. Never fails the script.
kill_pid() {
    local pid="$1" name="$2" i
    kill -0 "${pid}" 2>/dev/null || return 0
    log "stopping ${name} (pid ${pid})"
    kill "${pid}" 2>/dev/null
    for i in $(seq 1 20); do
        kill -0 "${pid}" 2>/dev/null || return 0
        sleep 0.5
    done
    log "${name} did not exit, sending SIGKILL"
    kill -9 "${pid}" 2>/dev/null
    sleep 1
}

backend_healthy() { curl -fsS --max-time 5 "${LOCAL_HEALTH}" >/dev/null 2>&1; }

# PIDs listening on our port whose working directory is the backend tree.
#
# Identity is taken from /proc/<pid>/cwd rather than from the command line.
# The backend can legitimately be launched as `./.venv/bin/python run.py`
# (relative) or with the interpreter's absolute path, and a pattern written for
# one silently fails to match the other — which leaves a stale server holding
# the port while the script reports success. The cwd is the same either way,
# and matching it also guarantees a process belonging to some other project is
# never killed just because it happens to sit on this port.
backend_pids_on_port() {
    local pid cwd
    for pid in $(ss -ltnpH 2>/dev/null \
                 | grep -F ":${PORT} " \
                 | grep -oP 'pid=\K[0-9]+' | sort -u); do
        cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null)"
        [[ "${cwd}" == "${APP_DIR}" ]] && echo "${pid}"
    done
}

# ── stop ─────────────────────────────────────────────────────────────────────

stop_backend() {
    if pid_alive "${BACKEND_PIDFILE}"; then
        kill_pid "$(cat "${BACKEND_PIDFILE}")" "backend"
    fi
    rm -f "${BACKEND_PIDFILE}"

    # Belt and braces: anything still holding our port from the backend tree,
    # including a server started by hand outside this script.
    local pid
    for pid in $(backend_pids_on_port); do
        kill_pid "${pid}" "backend on port ${PORT}"
    done

    # uvicorn's reloader/worker children outlive the parent occasionally.
    for pid in $(backend_pids_on_port); do
        kill -9 "${pid}" 2>/dev/null
    done
}

stop_ngrok() {
    if pid_alive "${NGROK_PIDFILE}"; then
        kill_pid "$(cat "${NGROK_PIDFILE}")" "ngrok"
    fi
    rm -f "${NGROK_PIDFILE}"

    # Any other agent holding OUR domain must go, or the tunnel below fails
    # with ERR_NGROK_334 ("endpoint already online"). On this machine that
    # includes the learning-platform chatbot's long-running tunnel — the free
    # plan has one domain and it now belongs to this backend.
    local holders
    holders="$(pgrep -f "ngrok .*${NGROK_DOMAIN}" 2>/dev/null || true)"
    for pid in ${holders}; do
        kill_pid "${pid}" "ngrok holding ${NGROK_DOMAIN}"
    done
    rm -f "${URL_FILE}"
}

# ── start ────────────────────────────────────────────────────────────────────

start_backend() {
    if backend_healthy; then
        log "backend already answering on ${LOCAL_HEALTH}"
        return 0
    fi

    [[ -x "${PYTHON}" ]] || die "no virtualenv python at ${PYTHON}"
    [[ -f "${APP_DIR}/run.py" ]] || die "no run.py in ${APP_DIR}"

    log "starting backend on port ${PORT}"
    (
        cd "${APP_DIR}" || exit 1
        PORT="${PORT}" nohup "${PYTHON}" run.py >>"${BACKEND_LOG}" 2>&1 &
        echo $! >"${BACKEND_PIDFILE}"
    )

    local i
    for i in $(seq 1 "${BACKEND_START_TIMEOUT}"); do
        if backend_healthy; then
            log "backend healthy after ${i}s (pid $(cat "${BACKEND_PIDFILE}"))"
            return 0
        fi
        if ! pid_alive "${BACKEND_PIDFILE}"; then
            log "backend process died on startup — last lines of ${BACKEND_LOG}:"
            tail -n 20 "${BACKEND_LOG}" || true
            return 1
        fi
        sleep 1
    done

    log "backend did not become healthy within ${BACKEND_START_TIMEOUT}s"
    tail -n 20 "${BACKEND_LOG}" || true
    return 1
}

# Ask ngrok's local API for the public URL of the tunnel pointing at our port.
ngrok_public_url() {
    curl -fsS --max-time 5 "http://${NGROK_WEB_ADDR}/api/tunnels" 2>/dev/null \
    | "${PYTHON}" -c '
import json, sys
try:
    tunnels = json.load(sys.stdin).get("tunnels", [])
except Exception:
    sys.exit(1)
port = sys.argv[1]
for t in tunnels:
    if t.get("proto") == "https" and str(port) in t.get("config", {}).get("addr", ""):
        print(t["public_url"]); sys.exit(0)
for t in tunnels:                       # fall back to any https tunnel
    if t.get("proto") == "https":
        print(t["public_url"]); sys.exit(0)
sys.exit(1)
' "${NGROK_TARGET_PORT}" 2>/dev/null
}

start_ngrok() {
    if [[ "${NGROK_ENABLED}" != "true" ]]; then
        log "ngrok disabled in config.env — backend is local-only on port ${PORT}"
        return 0
    fi

    command -v ngrok >/dev/null 2>&1 || die "ngrok not found on PATH"

    log "starting ngrok tunnel ${NGROK_DOMAIN} -> 127.0.0.1:${NGROK_TARGET_PORT}"
    nohup ngrok http "${NGROK_TARGET_PORT}" \
        --domain="${NGROK_DOMAIN}" \
        --log=stdout --log-format=logfmt \
        >>"${NGROK_LOG}" 2>&1 &
    echo $! >"${NGROK_PIDFILE}"

    local i url
    for i in $(seq 1 "${NGROK_START_TIMEOUT}"); do
        url="$(ngrok_public_url)"
        if [[ -n "${url}" ]]; then
            echo "${url}" >"${URL_FILE}"
            log "tunnel up after ${i}s: ${url}"
            return 0
        fi
        if ! pid_alive "${NGROK_PIDFILE}"; then
            log "ngrok exited on startup — last error from ${NGROK_LOG}:"
            grep -oE 'ERR_NGROK_[0-9]+|err="[^"]{0,200}' "${NGROK_LOG}" | tail -n 3 || true
            return 1
        fi
        sleep 1
    done

    log "ngrok did not report a public URL within ${NGROK_START_TIMEOUT}s"
    return 1
}

# ── verification + reporting ─────────────────────────────────────────────────

report() {
    local url="" public_state="n/a"
    [[ -f "${URL_FILE}" ]] && url="$(cat "${URL_FILE}")"

    if [[ -n "${url}" ]]; then
        if curl -fsS --max-time 15 "${url}${HEALTH_PATH}" >/dev/null 2>&1; then
            public_state="reachable"
        else
            public_state="NOT reachable"
        fi
    fi

    echo
    echo "──────────────────────────────────────────────────────────────────"
    echo "  YuviPep Salesforce AI backend"
    echo "──────────────────────────────────────────────────────────────────"
    printf "  local      : %s\n" "http://127.0.0.1:${PORT}"
    printf "  api docs   : %s\n" "http://127.0.0.1:${PORT}/docs"
    if [[ -n "${url}" ]]; then
        printf "  PUBLIC URL : %s   (%s)\n" "${url}" "${public_state}"
        printf "  DOWNLOADS  : %s/download/\n" "${url}"
        printf "  public docs: %s\n" "${url}/docs"
    else
        printf "  PUBLIC URL : (none — ngrok disabled or failed)\n"
    fi
    printf "  backend log: %s\n" "${BACKEND_LOG}"
    printf "  ngrok log  : %s\n" "${NGROK_LOG}"
    echo "──────────────────────────────────────────────────────────────────"
    echo
}

do_status() {
    if backend_healthy; then
        log "backend: UP    (${LOCAL_HEALTH})"
    else
        log "backend: DOWN  (${LOCAL_HEALTH})"
    fi
    if pid_alive "${NGROK_PIDFILE}"; then
        log "ngrok  : UP    (pid $(cat "${NGROK_PIDFILE}"))"
    else
        log "ngrok  : DOWN"
    fi
    report
}

# ── entry point ──────────────────────────────────────────────────────────────

case "${1:-restart}" in
    foreground)
        # systemd's entry point. Runs in the service cgroup.
        log "=== foreground start (systemd) ==="
        stop_ngrok
        stop_backend

        if [[ "${NGROK_ENABLED}" == "true" ]]; then
            # The tunnel must not be published before the backend can answer,
            # or the first caller through it gets a 502. Wait for health in a
            # child, then raise it. Staying inside the cgroup means systemd
            # cleans this up with everything else.
            (
                for _ in $(seq 1 "${BACKEND_START_TIMEOUT}"); do
                    backend_healthy && break
                    sleep 1
                done
                if backend_healthy; then
                    start_ngrok && report
                else
                    log "backend never became healthy; tunnel not started"
                fi
            ) &
        fi

        cd "${APP_DIR}" || die "cannot enter ${APP_DIR}"
        log "exec: PORT=${PORT} ${PYTHON} run.py"
        exec env PORT="${PORT}" "${PYTHON}" run.py
        ;;
    start|restart)
        log "=== ${1:-restart} requested ==="
        stop_ngrok
        stop_backend
        start_backend || die "backend failed to start"
        start_ngrok   || log "WARNING: tunnel failed; backend is still up locally"
        report
        ;;
    stop)
        log "=== stop requested ==="
        stop_ngrok
        stop_backend
        log "stopped"
        ;;
    status)
        do_status
        ;;
    url)
        [[ -f "${URL_FILE}" ]] && cat "${URL_FILE}" || { echo "no public URL" >&2; exit 1; }
        ;;
    *)
        echo "usage: $0 {start|stop|restart|status|url}" >&2
        exit 2
        ;;
esac
