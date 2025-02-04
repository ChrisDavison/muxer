#!/usr/bin/env python3
import logging
import os
import re
import subprocess
from argparse import ArgumentParser
from pathlib import Path
from typing import List

from iterfzf import iterfzf

HOME = Path.home()
WITHIN_TMUX = os.environ.get("TMUX")

logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.DEBUG)


class Muxer:
    name: str
    command: str
    dir: str

    def __init__(self, *, name, command, dir):
        self.name = name
        self.command = command
        self.dir = ["-c", dir] if dir else []

    def attach(self):
        log_and_run(["tmux", "attach", "-t", self.name])

    def switch(self):
        log_and_run(["tmux", "switch-client", "-t", self.name])

    def new_window(self):
        if WITHIN_TMUX:
            log_and_run(["tmux", "new-window", "-n", self.name, *self.dir, self.command])
        else:
            if not tmux_has_session(self.name):
                log_and_run(
                    [
                        "tmux",
                        "new-session",
                        "-A",
                        "-s",
                        self.name,
                        *self.dir,
                        self.command,
                    ]
                )
            self.attach()

    def new_session(self):
        if not tmux_has_session(self.name):
            flag = "-d" if WITHIN_TMUX else "-A"
            log_and_run(
                [
                    "tmux",
                    "new-session",
                    flag,
                    "-s",
                    self.name,
                    *self.dir,
                    self.command,
                ]
            )

        if WITHIN_TMUX:
            self.switch()
        else:
            self.attach()


def log_and_run(command):
    command = [c.strip() for c in command if c]
    logger.info("`" + " ".join(command) + "`")
    out = subprocess.run(command, capture_output=True)
    return out.stdout


def tmux_has_session(session):
    out = subprocess.run("tmux ls".split(), capture_output=True).stdout.decode()
    return re.search(f"\b{session}\b", out)


def get_local_directories(query="") -> List[str]:
    # read muxerrc
    muxerrc = Path("~/.muxer.rc").expanduser()
    candidates = ["~/notes", "~/Syncthing", "~/scratch", "~/code/*"]
    if muxerrc.exists():
        candidates = muxerrc.read_text().splitlines()
    directories = []
    excludes = set()
    for line in candidates:
        if line.startswith("!"):
            excludes.add(Path(line[1:]).expanduser())
        if line.endswith("*"):
            directories.extend(Path(line[:-1]).expanduser().glob("*"))
        else:
            directories.append(Path(line).expanduser())

    def valid(dir):
        return all(
            [
                query in dir.stem,
                dir.is_dir(),
                not dir.stem.startswith("."),
                dir not in excludes,
            ]
        )

    def relative(dir):
        return str(dir.relative_to(HOME))

    valid_dirs = filter(valid, directories)
    rel_to_home = map(relative, valid_dirs)
    return sorted(rel_to_home)


def get_ssh_hosts(query="") -> List[str]:
    candidates = []
    for line in (HOME / ".ssh" / "config").read_text().splitlines():
        if line.startswith("Host") and "*" not in line:
            for alias in line.split()[1:]:
                candidates.append(f"{alias}")
    if query:
        candidates = [c for c in candidates if query in c]
    return sorted(map(lambda x: "ssh: " + x, candidates))


def choose(listy, prompt, query=""):
    match listy:
        case []:
            return None
        case [only]:
            return only
        case multi:
            return iterfzf(
                multi,
                prompt=prompt,
                cycle=True,
                multi=False,
                query=query,
                case_sensitive=False,
            )


def main():
    parser = ArgumentParser()
    parser.add_argument("query", type=str, nargs="?", default="")
    parser.add_argument(
        "-w",
        "--window",
        action="store_true",
        help="Use a new window in current session, rather than a new session",
    )

    args = parser.parse_args()
    query = f"{args.query}" if args.query else ""

    candidates = get_ssh_hosts(query) + get_local_directories(query)
    prompt = "WINDOW > " if args.window else "SESSION > "
    chosen = choose(candidates, prompt=prompt, query=f"'{query}")
    if not chosen:
        print("Nothing chosen")
        return

    if chosen.startswith("ssh: "):
        chosen = chosen[5:]
        shellcommand = f" ssh {chosen}"
        dir = None
        name = f"SSH_{chosen}"
    else:
        shellcommand = None
        dir = str(HOME / chosen)
        name = (HOME / chosen).name

    # tmux_function = tmux_window if args.window else tmux_session
    muxer = Muxer(name=name, dir=dir, command=shellcommand)
    if args.window:
        muxer.new_window()
    else:
        muxer.new_session()
    # tmux_function(name, dir, shellcommand)
