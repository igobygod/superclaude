#!/usr/bin/env python3
"""Writes /var/lib/voice-tasks/capabilities.md: what Claude (the helper) can really use right now.

Runs as claude-helper (daily timer + at boot). First line "SUMMARY: ..." is put into every call's voice prompt,
so the voice assistant never claims Claude lacks access it actually has.
Sources: `claude mcp list` (connected only), the helper's skills, the Mac helpers.
"""
import os
import re
import subprocess
import time
from pathlib import Path

HOME = Path.home()
OUT = Path(os.environ.get("CAPS_OUT", "/var/lib/voice-tasks/capabilities.md"))
CLAUDE = str(HOME / ".local/bin/claude")
FRIENDLY = {
    "composio": "Composio (YouTube, Instagram, TikTok, Facebook and other connected apps)",
    "cloud-browser": "cloud browser with the owner's saved logins",
    "vidiq": "vidIQ (YouTube analytics and research)",
    "gmail": "Gmail (read, draft, send after confirmation)",
    "google drive": "Google Drive",
    "canva": "Canva",
    "claude docs": "Claude Docs",
    "telegram": "Telegram",
}
SKIP_SKILLS = re.compile(r"^(synced|gsap-|find-skills$|learned-server-status$)")


def connectors() -> tuple[list[str], list[str]]:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["PATH"] = f"{HOME}/.local/bin:{HOME}/.bun/bin:" + env.get("PATH", "/usr/bin:/bin")
    out = subprocess.run([CLAUDE, "mcp", "list"], cwd=HOME / "assistant", env=env, capture_output=True, text=True,
                         timeout=180).stdout
    ok, auth = [], []
    for line in out.splitlines():
        m = re.match(r"(?:claude\.ai |plugin:[\w-]+:)?([^:]+):", line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        name = FRIENDLY.get(key, m.group(1).strip())
        if "Connected" in line and name not in ok:
            ok.append(name)
        elif "Needs authentication" in line and name not in auth:
            auth.append(name)
    return ok, [a for a in auth if a not in ok]


def main() -> None:
    try:
        ok, auth = connectors()
    except Exception as e:  # keep the previous file if the check fails
        print("mcp list failed:", e)
        return
    skills = sorted(p.name for p in (HOME / ".claude/skills").iterdir() if p.is_dir() and not SKIP_SKILLS.match(p.name))
    mac = Path("/etc/mac-helpers/README.md").exists()
    extras = ["the owner's Mac through mac-run (their Mac Chrome, signed in; Xcode builds; files; iMessage)"] if mac else []
    extras += ["web search and web pages", "shell and files on the server"]
    summary = ("Claude can use: " + "; ".join(ok + extras) + "." +
               (f" Not signed in yet: {', '.join(auth)}." if auth else ""))
    OUT.write_text(
        f"SUMMARY: {summary}\n\n# What Claude can use (checked {time.strftime('%Y-%m-%d %H:%M')})\n\n"
        "## Connected tools\n" + "".join(f"- {c}\n" for c in ok) +
        ("\n## Needs sign-in\n" + "".join(f"- {a}\n" for a in auth) if auth else "") +
        "\n## Also\n" + "".join(f"- {e}\n" for e in extras) +
        "\n## Skills\n" + ", ".join(skills) + "\n")
    os.chmod(OUT, 0o664)
    print(summary)


if __name__ == "__main__":
    main()
