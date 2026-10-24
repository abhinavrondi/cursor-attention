#!/usr/bin/env python3
"""Speak a phrase while Cursor is waiting for approval.

The watcher tails Cursor's renderer logs on this Mac. It does not approve
anything, and it does not send the logs anywhere.
"""

from __future__ import annotations

import configparser
import fcntl
import glob
import os
import signal
import subprocess
import sys
import time

REQUESTED = b'reason="user-approval-requested"'
RESUMED = b'reason="agent-loop-resumed"'
MARKER_TAIL = max(len(REQUESTED), len(RESUMED)) - 1

SECTION = "approve-please"
ENV_CONFIG = "CURSOR_APPROVE_PLEASE_CONFIG"

DELAY_MIN = 0.0
DELAY_MAX = 600.0
REPEAT_MIN = 5.0
REPEAT_MAX = 600.0
POLL_MIN = 0.2
POLL_MAX = 5.0
PHRASE_MAX = 80
TITLE_MAX = 40
VOICE_MAX = 80


class ConfigError(Exception):
    """The settings file has a value this watcher will not use."""


def marker_pos(combined: bytes, needle: bytes, carry_len: int) -> int:
    """Return the start of the newest needle that ends in the new bytes.

    A marker that lived entirely in the carry was already handled. Returning
    -1 for that case stops a split-line buffer from firing on every poll.
    """
    pos = combined.rfind(needle)
    if pos < 0 or pos + len(needle) <= carry_len:
        return -1
    return pos


def transition(pending: bool, request_at: int, resumed_at: int) -> tuple[bool, str | None]:
    """Apply one log chunk to the waiting flag.

    A resume that lands after the request clears the wait. A later request
    starts a wait. Markers are indexes from marker_pos, or -1 when absent.
    """
    if request_at < 0 and resumed_at < 0:
        return pending, None
    if resumed_at > request_at:
        if pending:
            return False, "cancelled"
        return False, None
    if not pending:
        return True, "scheduled"
    return True, None


def consume_growth(size: int, offset: int) -> tuple[int, int | None]:
    """Return (new_offset, read_from). read_from is None when nothing is new.

    A shorter file was replaced. Skip what is already there.
    """
    if size < offset or size == offset:
        return size, None
    return size, offset


def _default_cursor_log_dir() -> str:
    return os.path.expanduser("~/Library/Application Support/Cursor/logs")


def _default_state_dir() -> str:
    return os.path.expanduser("~/.local/state/cursor-approve-please")


def _default_config_path() -> str:
    return os.path.expanduser("~/.config/cursor-approve-please/config.ini")


def discover_config_path() -> str | None:
    """Return the settings file to read, or None when the default is absent."""
    chosen = os.environ.get(ENV_CONFIG, "").strip()
    if chosen:
        return os.path.expanduser(chosen)
    default = _default_config_path()
    if os.path.isfile(default):
        return default
    return None


def _require_line(value: str, key: str, limit: int) -> str:
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ConfigError(f"{key} must be one line of at most {limit} characters")
    return value


def _require_voice(value: str) -> str:
    if not value:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -().'")
    if len(value) > VOICE_MAX or any(char not in allowed for char in value):
        raise ConfigError(f"voice must be a macOS voice name of at most {VOICE_MAX} characters")
    return value


def _require_number(value: str, key: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if number < low or number > high:
        raise ConfigError(f"{key} must be from {low:g} to {high:g}")
    return number


def _require_bool(value: str, key: str) -> bool:
    cleaned = value.strip().lower()
    if cleaned in ("yes", "true", "1", "on"):
        return True
    if cleaned in ("no", "false", "0", "off"):
        return False
    raise ConfigError(f"{key} must be yes or no")


class Config:
    def __init__(
        self,
        delay_seconds: float,
        repeat_seconds: float,
        poll_seconds: float,
        phrase: str,
        title: str,
        voice: str,
        sound: str,
        notify: bool,
        cursor_log_dir: str,
        state_dir: str,
        log_path: str,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.repeat_seconds = repeat_seconds
        self.poll_seconds = poll_seconds
        self.phrase = phrase
        self.title = title
        self.voice = voice
        self.sound = sound
        self.notify = notify
        self.cursor_log_dir = cursor_log_dir
        self.state_dir = state_dir
        self.log_path = log_path


def config_from_mapping(values: dict[str, str]) -> Config:
    """Build settings from the approve-please keys. Missing keys use defaults."""

    def pick(key: str, default: str) -> str:
        raw = values.get(key, default)
        if raw is None:
            return default
        return str(raw).strip()

    state_dir = pick("state_dir", "") or _default_state_dir()
    state_dir = os.path.expanduser(state_dir)
    log_path = pick("log_path", "") or os.path.join(state_dir, "watcher.log")
    log_path = os.path.expanduser(log_path)
    cursor_log_dir = pick("cursor_log_dir", "") or _default_cursor_log_dir()
    sound = os.path.expanduser(pick("sound", ""))
    return Config(
        delay_seconds=_require_number(pick("delay_seconds", "15"), "delay_seconds", DELAY_MIN, DELAY_MAX),
        repeat_seconds=_require_number(pick("repeat_seconds", "15"), "repeat_seconds", REPEAT_MIN, REPEAT_MAX),
        poll_seconds=_require_number(pick("poll_seconds", "0.4"), "poll_seconds", POLL_MIN, POLL_MAX),
        phrase=_require_line(pick("phrase", "Approve please"), "phrase", PHRASE_MAX),
        title=_require_line(pick("title", "Cursor"), "title", TITLE_MAX),
        voice=_require_voice(pick("voice", "")),
        sound=sound,
        notify=_require_bool(pick("notify", "yes"), "notify"),
        cursor_log_dir=os.path.expanduser(cursor_log_dir),
        state_dir=state_dir,
        log_path=log_path,
    )


def load_config(path: str | None = None) -> Config:
    """Read settings. An explicit missing file is an error. No file means defaults."""
    chosen = path if path is not None else discover_config_path()
    parser = configparser.ConfigParser(interpolation=None)
    if chosen:
        read = parser.read(chosen)
        if not read:
            raise ConfigError(f"cannot read {chosen}")
    section: dict[str, str] = {}
    if parser.has_section(SECTION):
        section = dict(parser.items(SECTION))
    elif chosen and parser.sections():
        raise ConfigError(f"{chosen} needs a [{SECTION}] section")
    return config_from_mapping(section)


def renderer_logs(cursor_log_dir: str) -> list[str]:
    pattern = os.path.join(cursor_log_dir, "*", "window*", "renderer.log")
    return sorted(glob.glob(pattern))


def make_logger(path: str):
    def log(line: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {line}\n")
        except OSError:
            pass

    return log


def acquire_lock(path: str, log) -> object:
    handle = open(path, "a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"already running, exiting pid {os.getpid()}")
        raise SystemExit(0)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def prepare_sound(cfg: Config) -> str:
    """Return an audio file for the phrase. A set sound path is used as-is."""
    if cfg.sound:
        if not os.path.isfile(cfg.sound):
            raise ConfigError(f"sound file not found: {cfg.sound}")
        return cfg.sound
    dest = os.path.join(cfg.state_dir, "phrase.aiff")
    stamp_path = os.path.join(cfg.state_dir, "phrase.txt")
    marker = cfg.phrase + "\n" + cfg.voice + "\n"
    current = ""
    if os.path.isfile(stamp_path):
        try:
            with open(stamp_path, encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            current = ""
    if current == marker and os.path.isfile(dest):
        return dest
    command = ["say", "-o", dest]
    if cfg.voice:
        command.extend(["-v", cfg.voice])
    command.append(cfg.phrase)
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigError("the say command could not speak the phrase") from exc
    try:
        with open(stamp_path, "w", encoding="utf-8") as handle:
            handle.write(marker)
    except OSError as exc:
        raise ConfigError(f"cannot write {stamp_path}") from exc
    return dest


def display_notification(phrase: str, title: str) -> None:
    subprocess.Popen(
        [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 1 of argv) with title (item 2 of argv)",
            "-e",
            "end run",
            "--",
            phrase,
            title,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_player(player) -> None:
    if player is not None and player.poll() is None:
        player.terminate()


def check(cfg: Config) -> int:
    logs = renderer_logs(cfg.cursor_log_dir)
    voice = cfg.voice or "system"
    sound = cfg.sound or "speak the phrase"
    print(f"phrase: {cfg.phrase}")
    print(f"title: {cfg.title}")
    print(f"delay_seconds: {cfg.delay_seconds:g}")
    print(f"repeat_seconds: {cfg.repeat_seconds:g}")
    print(f"poll_seconds: {cfg.poll_seconds:g}")
    print(f"notify: {'yes' if cfg.notify else 'no'}")
    print(f"voice: {voice}")
    print(f"sound: {sound}")
    print(f"cursor_log_dir: {cfg.cursor_log_dir}")
    print(f"state_dir: {cfg.state_dir}")
    print(f"renderer_logs: {len(logs)}")
    if cfg.sound and not os.path.isfile(cfg.sound):
        print(f"sound file not found: {cfg.sound}")
        return 1
    if not os.path.isdir(cfg.cursor_log_dir):
        print("cursor logs not found")
    return 0


def main() -> None:
    cfg = load_config()
    os.makedirs(cfg.state_dir, exist_ok=True)
    log = make_logger(cfg.log_path)
    lock = acquire_lock(os.path.join(cfg.state_dir, "watcher.lock"), log)
    sound = prepare_sound(cfg)
    stopping = False

    def request_stop(signum, frame) -> None:
        del signum, frame
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    offsets: dict[str, int] = {}
    carries: dict[str, bytes] = {}
    for path in renderer_logs(cfg.cursor_log_dir):
        try:
            offsets[path] = os.path.getsize(path)
        except OSError:
            offsets[path] = 0
    pending = False
    notified = False
    next_at = None
    player = None
    log(f"started pid {os.getpid()} watching {len(offsets)} renderer logs")
    while not stopping:
        live = renderer_logs(cfg.cursor_log_dir)
        live_set = set(live)
        for stale in list(offsets):
            if stale not in live_set:
                offsets.pop(stale, None)
                carries.pop(stale, None)
        for path in live:
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            offset = offsets.get(path, size)
            new_offset, read_from = consume_growth(size, offset)
            if read_from is None:
                if size < offset:
                    carries[path] = b""
                offsets[path] = new_offset
                continue
            try:
                with open(path, "rb") as handle:
                    handle.seek(read_from)
                    chunk = handle.read(new_offset - read_from)
            except OSError:
                chunk = b""
            offsets[path] = new_offset
            carry = carries.get(path, b"")
            combined = carry + chunk
            request_at = marker_pos(combined, REQUESTED, len(carry))
            resumed_at = marker_pos(combined, RESUMED, len(carry))
            carries[path] = combined[-MARKER_TAIL:] if combined else b""
            pending, event = transition(pending, request_at, resumed_at)
            if event == "cancelled":
                notified = False
                next_at = None
                stop_player(player)
                player = None
                log("cancelled")
            elif event == "scheduled":
                notified = False
                next_at = time.time() + cfg.delay_seconds
                log("scheduled")
        if pending and next_at is not None and time.time() >= next_at:
            if player is None or player.poll() is not None:
                player = subprocess.Popen(
                    ["afplay", sound],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if not notified:
                    if cfg.notify:
                        display_notification(cfg.phrase, cfg.title)
                    notified = True
                    log("chime")
                else:
                    log("chime again")
            next_at = time.time() + cfg.repeat_seconds
        time.sleep(cfg.poll_seconds)
    stop_player(player)
    log("stopped")
    lock.close()


def entry() -> None:
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--check":
            raise SystemExit(check(load_config()))
        if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
            print("Usage: approve_please.py [--check]")
            raise SystemExit(0)
        if len(sys.argv) > 1:
            print("Usage: approve_please.py [--check]", file=sys.stderr)
            raise SystemExit(2)
        main()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    entry()
