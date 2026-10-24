# Approve please

A small Mac watcher. When Cursor shows an approval card and you do not click it, this says “Approve please,” then says it again until you do.

The first reminder waits 15 seconds. Later reminders are 15 seconds apart. A click cancels the current one. One notification is posted the first time. Later reminders are sound only.

It stays on your Mac. It reads Cursor’s local renderer logs and does not send them anywhere. It does not click Approve for you.

Cursor does not yet offer a hook for “waiting for approval,” so this watches log lines Cursor writes for that card. A Cursor update can change those lines, and then the reminders stop until this project catches up.

## Requirements

- macOS
- Python 3.9 or newer
- `say`, `afplay`, and `osascript`, which come with macOS

## Install

```sh
git clone https://github.com/abhinavrondi/cursor-approve-please.git
cd cursor-approve-please
./install.sh
```

That copies the script to `~/.local/share/cursor-approve-please/`, writes a login agent named `local.cursor-approve-please`, and starts it. Settings go to `~/.config/cursor-approve-please/config.ini` only when that file is missing.

If another approval watcher is already running, unload it first. Two watchers will both speak.

Check the settings without playing a sound:

```sh
python3 ~/.local/share/cursor-approve-please/approve_please.py --check
```

## Settings

Edit `~/.config/cursor-approve-please/config.ini`. The example in this repo is `config.example.ini`.

| Setting | Default | What it does |
| --- | --- | --- |
| `delay_seconds` | `15` | Wait after the card appears. `0` to `600`. |
| `repeat_seconds` | `15` | Gap between repeats while the card is open. `5` to `600`. |
| `poll_seconds` | `0.4` | How often to read new log lines. `0.2` to `5`. |
| `phrase` | `Approve please` | Spoken line and notification text. One line, at most 80 characters. |
| `title` | `Cursor` | Notification title. |
| `voice` | empty | macOS voice for `say`, such as `Samantha`. Empty uses the system voice. |
| `sound` | empty | Path to an audio file. Empty speaks `phrase` with `say`. |
| `notify` | `yes` | Post one notification when a wait starts. |
| `cursor_log_dir` | empty | Cursor’s log folder. Empty uses `~/Library/Application Support/Cursor/logs`. |

After a change, reload the watcher:

```sh
launchctl kickstart -k "gui/$(id -u)/local.cursor-approve-please"
```

`CURSOR_APPROVE_PLEASE_CONFIG` can point at a different settings file. The login agent does not load your shell profile, so put day-to-day settings in the config file.

The watcher log is `~/.local/state/cursor-approve-please/watcher.log`. It records start, schedule, cancel, and chime. It does not copy Cursor’s logs.

## If it stays quiet

1. Run the check command above. It should list one or more renderer logs. “cursor logs not found” means Cursor has not written logs yet, or the log folder moved.
2. Open the watcher log. A waiting card adds `scheduled`, then `chime`. A click adds `cancelled`.
3. If the card is on screen and the log never says `scheduled`, Cursor changed the line this project watches. Open an issue and include the Cursor version. Do not paste a renderer log. It can contain private text from the chat.

Cursor users have asked for a real “waiting for approval” hook [on the forum](https://forum.cursor.com/t/fire-a-hook-when-agent-waits-for-command-tool-approval/166947). This project is the Mac workaround until that exists.

## Uninstall

```sh
./uninstall.sh
```

Settings and the log stay. Remove those too with `./uninstall.sh --purge`.

## Develop

```sh
python3 -m unittest discover -s tests -v
```

The tests cover the wait/cancel rules and the settings checks. They do not play sound.

## License

MIT. See `LICENSE`.
