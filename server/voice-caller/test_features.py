"""Offline tests for the voice features (no calls, no Gemini, no Claude).
Run: cd /srv/voice-caller && venv/bin/python -m unittest test_features -v
Uses temp dirs in place of /var/lib/voice-tasks etc.
"""

import asyncio
import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("VOICECALLER_STATE", tempfile.mkdtemp())
os.environ.setdefault("AGENT_TZ", "America/New_York")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent  # noqa: E402
import watcher  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class AgentTools(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "queue").mkdir()
        self.patches = [mock.patch.object(agent, n, v) for n, v in {
            "TASKS": self.tmp, "PROFILE": self.tmp / "profile.md", "STOP_FILE": self.tmp / "STOP",
            "WATCHES": self.tmp / "watches", "INTERVIEWS": self.tmp / "interviews",
            "EMAIL_QUEUE": self.tmp / "mail.jsonl", "CALLS_LOG": self.tmp / "calls.jsonl",
            "STATE": self.tmp, "PRONOUNCE": self.tmp / "pron.json"}.items()]
        self.cli_calls, self.cli_result = [], (-1, "")

        async def fake_cli(args, timeout=15):
            self.cli_calls.append(args)
            r = self.cli_result
            return r(args) if callable(r) else r
        self.patches += [mock.patch.object(agent, "tool_cli", fake_cli),
                         mock.patch.object(agent, "tool_cli_sync", lambda a, t=5: (0, "MEMORY: goal X") if a[1] == "context"
                                           else (0, "q1 [open] decide: send the CV?") if a[0] == "voice-questions"
                                           else (0, "5h: 16%, week: 76%"))]
        for p in self.patches:
            p.start()
        (self.tmp / "profile.md").write_text("# About the owner\n- Name: Test\n")
        self.a = agent.Assistant({"call_id": "call-test", "reason": "test"})

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def tool(self, name, *args, **kw):
        fn = getattr(agent.Assistant, name)
        fn = getattr(fn, "__wrapped__", None) or getattr(fn, "_func", None) or fn
        return run(fn(self.a, None, *args, **kw))

    def test_idle_watch_asks_then_hangs_up(self):
        said, hung = [], []
        sess = mock.Mock(agent_state="listening")
        async def gen(instructions): said.append(instructions)
        sess.generate_reply = gen
        async def fake_hang(room, why): hung.append(why)
        async def go():
            with mock.patch.object(agent, "IDLE_ASK", 0.2), mock.patch.object(agent, "IDLE_HANGUP", 0.2), \
                 mock.patch.object(agent, "hang_up", fake_hang), mock.patch.object(agent.asyncio, "sleep", real_sleep_short):
                await asyncio.wait_for(agent.watch_idle(sess, self.a, "r1", time.time(), 0), 5)
        real_sleep = asyncio.sleep
        async def real_sleep_short(t): await real_sleep(0.05)
        asyncio.run(go())
        self.assertEqual(said, ["Say only: Are you still there?"])
        self.assertEqual(hung, ["no answer to are-you-still-there"])

    def test_prompt_has_capabilities_and_rules(self):
        self.assertIn("NEVER say Claude can't do something", self.a.instructions)
        self.assertIn("go on", self.a.instructions)
        with mock.patch.object(agent, "CAPABILITIES", self.tmp / "caps.md"):
            (self.tmp / "caps.md").write_text("SUMMARY: Claude can use: vidIQ; cloud browser.\n\n# rest")
            self.assertEqual(agent.capabilities(), "Claude can use: vidIQ; cloud browser.")
            (self.tmp / "caps.md").unlink()
            self.assertIn("logins", agent.capabilities())

    def test_style_and_personality_in_prompt(self):
        for phrase in ("STYLE ON REQUEST ONLY", "in a hurry", "just listen", "I'm driving", "Right away.",
                       "no, I meant", "Don't claim to be any fictional character"):
            self.assertIn(phrase, self.a.instructions)

    def test_pronunciation_saved_and_used(self):
        self.assertIn("Not saved", self.tool("set_pronunciation", "Okafor", "oh-KAH-for"))
        self.assertFalse((self.tmp / "pron.json").exists())
        self.tool("set_pronunciation", "Okafor", "oh-KAH-for", True)
        self.assertEqual(json.loads((self.tmp / "pron.json").read_text()), {"Okafor": "oh-KAH-for"})
        self.assertIn("Okafor = oh-KAH-for", agent.pronunciations())
        self.assertEqual(self.cli_calls[-1][:4], ["voice-memory", "remember", "--fact", "Pronounce Okafor as oh-KAH-for"])

    def test_switch_to_text(self):
        self.cli_result = (0, "")
        out = self.tool("switch_to_text", "Interview at 3:30; prep note on Telegram.")
        self.assertEqual(self.cli_calls[-1][:3], ["voice-notify", "--level", "info"])
        self.assertIn("end_call", out)

    def test_working_sounds_tool(self):
        with mock.patch.object(agent, "SOUNDS", self.tmp):
            self.assertEqual(self.tool("working_sounds", "off"), "Sounds off.")
            self.assertTrue(agent.sound_prefs()["off"])
            self.assertEqual(self.tool("working_sounds", "on"), "Sounds back on.")
            self.assertFalse(agent.sound_prefs()["off"])
            self.a.sounds = mock.Mock(change=lambda: "Changed.", rate=lambda like: "rated")
            self.assertEqual(self.tool("working_sounds", "change"), "Changed.")
            self.assertEqual(self.tool("working_sounds", "never"), "rated")

    def test_talking_speed_changes_prompt_pace(self):
        with mock.patch.object(agent, "VOICE_PREFS", self.tmp / "vp.json"), \
             mock.patch.object(agent.Assistant, "session", types.SimpleNamespace(output=types.SimpleNamespace(audio=None))):
            out = self.tool("talking_speed", "faster")
            self.assertIn("FAST", out)
            self.assertEqual(agent.speak_speed(), 1.3)
            self.assertIn("fastest", self.tool("talking_speed", "faster"))
            self.tool("talking_speed", "normal")
            self.assertEqual(agent.pace_line(), agent.PACES[1.15])

    def test_stop_everything_rule(self):
        self.assertIn("ONLY when the owner explicitly says to stop or cancel", self.a.instructions)

    def test_honesty_and_pronunciation_rules(self):
        for phrase in ("HONESTY (top rule)", "never read it out", "I can't say that one", "Never loop on"):
            self.assertIn(phrase, self.a.instructions)

    def test_pronunciation_options_spawns_sender(self):
        with mock.patch.object(agent.subprocess, "Popen") as pop:
            self.assertIn("at least", "at least") if False else None
            out = self.tool("pronunciation_options", "Alex", ["Al-ex", "Ah-lex", "Al-icks", "Ay-lex"])
        args = pop.call_args[0][0]
        self.assertTrue(args[1].endswith("pron_options.py"))
        self.assertEqual((args[2], json.loads(args[3])), ("Alex", ["Al-ex", "Ah-lex", "Al-icks", "Ay-lex"]))
        self.assertIn("Telegram", out)
        self.assertIn("4 or 5", self.tool("pronunciation_options", "X", ["a"]))

    def test_speed_limit_is_honest(self):
        with mock.patch.object(agent, "VOICE_PREFS", self.tmp / "vp2.json"), \
             mock.patch.object(agent.Assistant, "session", types.SimpleNamespace(output=types.SimpleNamespace(audio=None))):
            self.assertIn("Pace setting changed", self.tool("talking_speed", "faster"))
            self.assertIn("No change possible", self.tool("talking_speed", "faster"))
            self.assertEqual(agent.speak_speed(), 1.3)

    def test_sent_media(self):
        img = self.tmp / "x.png"
        img.write_bytes(b"png")
        items = [{"id": "1", "time": time.time() - 30, "source": "imessage", "type": "image", "path": str(img),
                  "caption": "what is this?", "name": "x.png"}]
        self.cli_result = lambda a: (0, json.dumps(items)) if a[0] == "voice-media" else (0, "")
        async def fake_describe(path, kind, q):
            return f"A blue square ({kind}, {q})"
        with mock.patch.object(agent, "describe_media", fake_describe):
            out = self.tool("look_at_sent_media")
        self.assertIn("A blue square (image, what is this?)", out)
        self.cli_result = (0, "[]")
        self.assertIn("Nothing has come in", self.tool("look_at_sent_media"))
        items[0].update(type="video", path="/v.mp4")
        self.cli_result = lambda a: (0, json.dumps(items)) if a[0] == "voice-media" else (0, "")
        self.tool("look_at_sent_media", "best moments?")
        q = [t for t in self.queued() if "voice-video-review" in t["task"]]
        self.assertEqual(len(q), 1)
        self.assertIn("/v.mp4", q[0]["task"])

    def test_entrypoint_runner_intact(self):
        self.assertTrue(hasattr(agent.cli, "run_app"))  # helpers must never shadow livekit's cli

    def yes(self, reply="Yes."):
        self.a.said.append((time.time() - 1, "Shall I send it?"))
        self.a.heard.append((time.time(), reply))

    def test_go_ahead_words_are_accepted(self):
        for reply in ("Just send it.", "sure thing", "Okay then", "go ahead", "yeah do it", "Okay."):
            self.a.said, self.a.heard = [], []
            self.yes(reply)
            self.assertTrue(asyncio.run(self.a.owner_said_yes(0.1)), reply)

    def test_send_without_readback_is_refused(self):
        self.a.heard.append((time.time(), "yes"))  # a yes, but nothing was read back
        out = self.tool("send_imessage", "+15555550100", "hi", True)
        self.assertIn("couldn't find the owner's yes", out)
        self.assertEqual(self.queued(), [])

    def test_stop_needs_words_or_confirmed_yes(self):
        self.a.heard.append((time.time(), "accidentally said yes to thank you email"))
        self.assertIn("Stop all tasks?", self.tool("stop_everything"))
        self.assertFalse((self.tmp / "STOP").exists())
        self.a.said.append((time.time(), "Stop all tasks?"))
        self.a.heard.append((time.time() + 0.1, "yes"))
        self.tool("stop_everything", True)
        self.assertTrue((self.tmp / "STOP").exists())

    def test_claim_guard_flags_fake_speed_change(self):
        sess = FakeSession()
        replies = []
        async def gen(instructions): replies.append(instructions)
        sess.generate_reply = gen
        g = agent.ClaimGuard(sess, self.a, "call-test")

        async def go():
            g.on_item(types.SimpleNamespace(item=types.SimpleNamespace(role="assistant",
                                            text_content="I have increased my speaking speed. How is this?")))
            await asyncio.sleep(0.05)
            self.a.tool_ok["talking_speed"] = time.time()
            g.on_item(types.SimpleNamespace(item=types.SimpleNamespace(role="assistant",
                                            text_content="I'll speak quicker, my pace is faster now.")))
            await asyncio.sleep(0.05)
        asyncio.run(go())
        self.assertEqual(len(replies), 1)
        self.assertIn("did not actually change", replies[0])

    def test_lessons_in_prompt(self):
        with mock.patch.object(agent, "LESSONS", self.tmp / "lessons.md"):
            (self.tmp / "lessons.md").write_text("- Never say the email address out loud.")
            self.assertIn("Never say the email address", agent.lessons())

    def test_profile_in_instructions(self):
        self.assertIn("Name: Test", self.a.instructions)

    def test_prompt_has_memory_and_questions(self):
        self.assertIn("MEMORY: goal X", self.a.instructions)
        self.assertIn("send the CV?", self.a.instructions)

    def test_remember_via_memory(self):
        self.cli_result = (0, "Saved: 1")
        self.tool("remember", "Passport renewal is in March", True, "2027-03-31")
        a = self.cli_calls[-1]
        self.assertEqual(a[:4], ["voice-memory", "remember", "--fact", "Passport renewal is in March"])
        self.assertIn("--private", a)
        self.assertEqual(a[a.index("--source") + 1], "said")
        self.assertEqual(a[a.index("--expires") + 1], "2027-03-31")
        self.assertNotIn("Passport", (self.tmp / "profile.md").read_text())

    def test_private_never_falls_back_to_profile(self):
        out = self.tool("remember", "Passport number is X", True)
        self.assertIn("Couldn't save", out)
        self.assertNotIn("Passport", (self.tmp / "profile.md").read_text())

    def test_recall_answer_usage(self):
        self.cli_result = (0, "Jordan said Tuesday.")
        self.assertIn("Jordan said Tuesday.", self.tool("recall", "what did Jordan say"))
        self.cli_result = lambda a: (3, "already done ✓ (answered via imessage)") if a[0] == "voice-questions" else (0, "")
        self.assertIn("Already handled", self.tool("answer_question", "q1", "yes"))
        self.cli_result = lambda a: (4, "no such question") if a[0] == "voice-questions" else (0, "Saved: 1")
        self.assertEqual(self.tool("answer_question", "m7", "yes"), "Saved.")
        self.assertEqual(self.cli_calls[-1], ["voice-memory", "answer", "m7", "yes"])
        self.cli_result = (0, "5h: 16%, week: 76%")
        self.assertIn("76%", self.tool("usage_left"))

    def test_usage_guard(self):
        with mock.patch.object(agent, "usage_pct", lambda: 93.0):
            self.assertIn("93%", self.tool("give_task_to_claude", "big job", hard=True))
            self.assertEqual(self.queued(), [])
            self.assertIn("93%", self.tool("mac_task", "build"))
            self.tool("give_task_to_claude", "small job")  # normal tasks aren't held
            self.tool("give_task_to_claude", "big job", hard=True, force=True)
        self.assertEqual(len(self.queued()), 2)

    def test_remember_appends(self):
        self.tool("remember", "Signs emails as Alex")
        self.tool("remember", "Prefers short emails")
        text = (self.tmp / "profile.md").read_text()
        self.assertEqual(text.count("## Learned on calls"), 1)
        self.assertIn("- Signs emails as Alex", text)
        self.assertIn("- Prefers short emails", text)

    def test_stop_and_resume(self):
        self.a.heard.append((time.time(), "Stop everything now"))
        self.tool("stop_everything")
        self.assertTrue((self.tmp / "STOP").exists())
        out = self.tool("give_task_to_claude", "do x")
        self.assertIn("paused", out)
        self.assertEqual(list((self.tmp / "queue").glob("*.json")), [])
        self.tool("resume_tasks")
        self.assertFalse((self.tmp / "STOP").exists())
        self.tool("give_task_to_claude", "do x")
        self.assertEqual(len(list((self.tmp / "queue").glob("*.json"))), 1)

    def test_emails(self):
        with (self.tmp / "mail.jsonl").open("w") as f:
            f.write(json.dumps({"time": time.time() - 600, "from": "Old <o@example.com>", "subject": "old", "body": "b1"}) + "\n")
            f.write(json.dumps({"time": time.time() - 60, "from": "Jordan <j@shop.example.com>", "subject": "Interview",
                                "body": "Can you do Tuesday?", "thread": "18abc"}) + "\n")
        lst = self.tool("recent_emails")
        self.assertTrue(lst.startswith("1. 1 min ago from Jordan"))
        one = self.tool("read_email", 1)
        self.assertIn("Can you do Tuesday?", one)
        self.assertIn("Gmail thread: 18abc", one)
        self.assertIn("No email", self.tool("read_email", 9))

    def test_watch(self):
        self.tool("watch_for_reply", "Jordan at Acme", "interview time", 3)
        files = list((self.tmp / "watches").glob("*.json"))
        self.assertEqual(len(files), 1)
        w = json.loads(files[0].read_text())
        self.assertEqual(w["who"], "Jordan at Acme")
        self.assertAlmostEqual(w["expires"] - w["created"], 3 * 86400, delta=5)

    def test_debrief(self):
        self.tool("save_interview_debrief", "Acme", "Went well, asked about SwiftUI", "Jordan")
        notes = list((self.tmp / "interviews").glob("*-acme.md"))
        self.assertEqual(len(notes), 1)
        q = [json.loads(f.read_text()) for f in (self.tmp / "queue").glob("*.json")]
        self.assertEqual(len(q), 1)
        self.assertFalse(q[0]["callback"])
        self.assertIn("DRAFT", q[0]["task"])
        self.assertIn("Do NOT send", q[0]["task"])


    def queued(self):
        return [json.loads(f.read_text()) for f in (self.tmp / "queue").glob("*.json")]

    def test_imessage_needs_confirmation(self):
        self.assertIn("Need a phone number", self.tool("send_imessage", "mom", "hi", True))
        self.assertIn("Shall I send it", self.tool("send_imessage", "+1 555-555-0100", "hi"))
        self.assertEqual(self.queued(), [])
        self.yes()
        self.tool("send_imessage", "+1 555-555-0100", "hi there", True)
        q = self.queued()
        self.assertEqual((q[0]["kind"], q[0]["to"], q[0]["text"], q[0]["confirmed"]), ("imessage", "+15555550100", "hi there", True))

    def test_confirmed_flag_on_claude_task(self):
        self.yes()
        self.tool("give_task_to_claude", "send x", owner_confirmed=True)
        self.tool("give_task_to_claude", "look y")
        q = sorted(self.queued(), key=lambda t: t["task"])
        self.assertEqual([t["confirmed"] for t in q], [False, True])
        self.assertIn("The owner confirmed by voice", q[1]["task"])

    def test_mac_tools(self):
        self.tool("mac_task", "build it", "~/Documents/Demo App", False, 90)
        self.tool("list_mac_sessions")
        self.tool("mac_status")
        self.tool("resume_mac_session", " abc123 ", "continue")
        kinds = {t["kind"]: t for t in self.queued()}
        self.assertEqual(set(kinds), {"mac", "mac_sessions", "mac_running", "mac_resume"})
        self.assertEqual(kinds["mac"]["timeout"], 3600)
        self.assertFalse(kinds["mac"]["full"])
        self.assertEqual(kinds["mac_resume"]["session"], "abc123")


    def test_profile_not_cut_from_the_front(self):
        (self.tmp / "profile.md").write_text("FIRST-FACT\n" + "x" * 5000 + "\nLAST-FACT\n")
        self.assertIn("FIRST-FACT", agent.profile_text())
        self.assertIn("LAST-FACT", agent.profile_text())
        (self.tmp / "profile.md").write_text("FIRST-FACT\n" + "x" * 9000)
        with self.assertLogs("pa-caller", "WARNING"):
            t = agent.profile_text()
        self.assertTrue(t.startswith("FIRST-FACT") and t.endswith("[profile truncated]"))

    def test_session_steering(self):
        self.assertIn("Shall I send it", self.tool("send_to_session", "Demo", "add dark mode"))
        self.assertEqual(self.queued(), [])
        self.yes()
        self.tool("send_to_session", "Demo", "add dark mode", True)
        self.tool("live_mac_sessions")
        kinds = {t["kind"]: t for t in self.queued()}
        self.assertEqual(kinds["mac_message"]["session"], "Demo")
        self.assertIn("mac_agents", kinds)

    def fake_ask_server(self, delay, answer="Your interview is at 3."):
        sock = self.tmp / "ask.sock"
        async def handle(r, w):
            req = json.loads(await r.readline())
            self.asked = req
            await asyncio.sleep(delay)
            w.write((json.dumps({"answer": answer}) + "\n").encode()); await w.drain(); w.close()
        async def go(call):
            srv = await asyncio.start_unix_server(handle, str(sock))
            async with srv:
                return await call()
        return sock, go

    def test_ask_claude_quick_and_slow(self):
        sock, go = self.fake_ask_server(0.1)
        fn = agent.Assistant.ask_claude
        fn = getattr(fn, "__wrapped__", None) or getattr(fn, "_func", None) or fn
        with mock.patch.object(agent, "ASK_SOCK", sock):
            out = asyncio.run(go(lambda: fn(self.a, None, "when is my interview?")))
            self.assertIn("Your interview is at 3.", out)
            self.assertEqual(self.asked["op"], "ask")
            sock2, go2 = self.fake_ask_server(1.0)
            with mock.patch.object(agent, "ASK_SOCK", sock2), mock.patch.object(agent, "ASK_WAIT", 0.3):
                out = asyncio.run(go2(lambda: fn(self.a, None, "slow one")))
            self.assertIn("needs a bit longer", out)
            self.assertIn(self.asked["tid"], self.a.my_tasks)
        with mock.patch.object(agent, "ASK_SOCK", self.tmp / "missing.sock"):
            out = asyncio.run(fn(self.a, None, "no server"))
        self.assertIn("task", out)
        self.assertTrue(any("no server" in t["task"] for t in self.queued()))


class Runner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.environ.get("TASK_RUNNER", "/usr/local/lib/voice-tasks/task_runner.py")
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_runner.py")
        spec = importlib.util.spec_from_file_location("tr", path)
        cls.tr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tr)

    def test_send_tools_only_when_confirmed(self):
        j = Path("/tmp/j.md")
        plain = self.tr.build_command({"task": "x"}, j)[0]
        conf = self.tr.build_command({"task": "x", "confirmed": True}, j)[0]
        self.assertNotIn("mcp__claude_ai_Gmail__send_message", plain)
        self.assertIn("mcp__claude_ai_Gmail__create_draft", plain)
        self.assertIn("mcp__claude_ai_Gmail__send_message", conf)

    def test_mac_commands(self):
        j = Path("/tmp/j.md")
        cmd = self.tr.build_command({"task": "go", "kind": "mac", "folder": "~/P", "full": True, "timeout": 600}, j)[0]
        self.assertNotIn("--full", cmd)  # full needs confirmed too
        self.assertEqual(cmd[-3:], ["-d", "~/P", "go"])
        cmd = self.tr.build_command({"task": "go", "kind": "mac_resume", "session": "s1"}, j)[0]
        self.assertEqual(cmd[-3:], ["-r", "s1", "go"])
        self.assertEqual(self.tr.build_command({"task": "", "kind": "imessage", "to": "+1", "text": "t"}, j)[0][-2:], ["+1", "t"])

    def test_blocked_send_is_not_success(self):
        out = json.dumps({"result": "SPOKEN: Sent it.", "is_error": False,
                          "permission_denials": [{"tool_name": "mcp__claude_ai_Gmail__send_message"}]})
        result, ok = self.tr.interpret({"task": "x"}, 0, out, "")
        self.assertFalse(ok)
        self.assertTrue(result.startswith("SPOKEN: A send was blocked"))

    def test_mac_results(self):
        r, ok = self.tr.interpret({"task": "x", "kind": "mac"}, 75, "", "unreachable")
        self.assertFalse(ok)
        self.assertIn("couldn't reach your Mac", r)
        r, ok = self.tr.interpret({"task": "x", "kind": "mac"}, 0, "did it\nSPOKEN: Built fine.", "")
        self.assertTrue(ok)
        self.assertTrue(r.startswith("SPOKEN: Built fine."))
        r, ok = self.tr.interpret({"task": "x", "kind": "imessage", "to": "+1"}, 0, "sent\n", "")
        self.assertTrue(ok)


    def test_mac_message_command(self):
        cmd = self.tr.build_command({"task": "", "kind": "mac_message", "session": "Demo", "text": "add dark mode"}, Path("/tmp/j"))[0]
        self.assertIn("haiku", cmd)
        self.assertIn("'Demo'", cmd[-1])
        self.assertIn("add dark mode", cmd[-1])
        self.assertIn("never answer or approve any permission prompt", cmd[-1])

    def test_dashboard_stop_and_helpers(self):
        import tempfile
        base = Path(tempfile.mkdtemp())
        fake = base / "claude"
        fake.write_text("#!/bin/sh\nkill -TERM $$\n")
        fake.chmod(0o755)
        calls = []
        tr = self.tr
        with mock.patch.multiple(tr, CLAUDE=str(fake), JOBS=base, DONE=base, ASSISTANT=base, STOP=base / "STOP",
                                 helper=lambda a, stdin=None: calls.append(a)):
            run = base / "x.json"
            run.write_text(json.dumps({"id": "d1", "task": "t", "callback": True}))
            tr.run_task(run)
        d = json.loads((base / "d1.json").read_text())
        self.assertEqual((d["spoken"], d["ok"], d["callback"]), ("That task was stopped from the dashboard.", False, False))
        self.assertEqual(calls[0][:2], ["voice-usage", "record"])
        self.assertEqual(calls[-1][:6], ["voice-memory", "journal", "--source", "task", "--id", "d1"])

    def test_local_only_routing(self):
        self.assertTrue(self.tr.local_only("How many files are in jobs/? Reply with just the number."))
        for t in ("Check my Gmail for the newest email", "count my emails", "post the clip to YouTube",
                  "search the web for the weather", "List the features of the Notes app."):
            self.assertFalse(self.tr.local_only(t), t)
        cmd = self.tr.build_command({"task": "How many files are in jobs/?"}, Path("/tmp/j"))[0]
        self.assertIn("--strict-mcp-config", cmd)
        cmd = self.tr.build_command({"task": "Check my Gmail"}, Path("/tmp/j"))[0]
        self.assertNotIn("--strict-mcp-config", cmd)
        self.assertTrue(cmd[2].startswith("Job file for UPDATE lines: /tmp/j"))

    def test_warm_spare_runs_one_task_isolated(self):
        import tempfile
        base = Path(tempfile.mkdtemp())
        fake = base / "claude"
        fake.write_text("#!/usr/bin/env python3\nimport sys, json\n"
                        "line = sys.stdin.readline()\nmsg = json.loads(line)['message']['content']\n"
                        "print(json.dumps({'type': 'system', 'subtype': 'init'}))\n"
                        "print(json.dumps({'type': 'result', 'is_error': False, 'result': 'SPOKEN: did ' + msg.splitlines()[-1]}), flush=True)\n"
                        "sys.stdin.read()\n")
        fake.chmod(0o755)
        tr = self.tr
        (base / "jobs").mkdir(); (base / "done").mkdir()
        calls = []
        with mock.patch.multiple(tr, CLAUDE=str(fake), JOBS=base / "jobs", DONE=base / "done", ASSISTANT=base,
                                 STOP=base / "STOP", helper=lambda a, stdin=None: calls.append(a)):
            tr.SPARE.clear()
            tr.ensure_spare()
            first = tr.SPARE["proc"]
            run = base / "t.json"
            run.write_text(json.dumps({"id": "w1", "task": "count the notes", "callback": False}))
            tr.run_task(run)
            d = json.loads((base / "done" / "w1.json").read_text())
            self.assertEqual((d["ok"], d["spoken"]), (True, "did count the notes"))
            self.assertIn("warm", (base / "jobs" / "voice-w1.md").read_text())
            self.assertNotIn("proc", tr.SPARE)          # used up: never reused for another task
            tr.ensure_spare()
            self.assertIsNot(tr.SPARE["proc"], first)   # a fresh one replaces it
            self.assertIsNone(tr.take_spare({"task": "x", "confirmed": True}))  # confirmed sends: cold start
            self.assertIsNone(tr.take_spare({"task": "x", "model": "opus"}))
            tr.kill(tr.SPARE.pop("proc")); tr.SPARE.clear()

    def test_mac_look_command(self):
        cmd = self.tr.build_command({"task": "Did the build finish?", "kind": "mac_look"}, Path("/tmp/j"))[0]
        self.assertIn("Did the build finish?", cmd[-1])
        self.assertIn("mac-look.py --clean", cmd[-1])
        r, ok = self.tr.interpret({"task": "x", "kind": "mac_look"}, 0, "blah\nSPOKEN: Xcode shows Build Succeeded.", "")
        self.assertEqual((r.splitlines()[0], ok), ("SPOKEN: Xcode shows Build Succeeded.", True))

    def test_ask_server_end_to_end(self):
        import tempfile, socket as so, threading as th
        base = Path(tempfile.mkdtemp())
        fake = base / "claude"
        fake.write_text("#!/usr/bin/env python3\nimport sys, json, time\n"
                        "for line in sys.stdin:\n    q = json.loads(line)['message']['content']\n"
                        "    time.sleep(1.0 if 'slow' in q else 0)\n"
                        "    print(json.dumps({'type': 'assistant'})); print(json.dumps({'type': 'result', 'result': 'echo ' + q}), flush=True)\n")
        fake.chmod(0o755)
        tr = self.tr
        for name, val in {"BASE": base, "ASK_SOCK": base / "ask.sock", "CLAUDE": str(fake), "JOBS": base / "jobs",
                          "DONE": base / "done", "STOP": base / "STOP", "ASSISTANT": base}.items():
            setattr(tr, name, val)
        (base / "jobs").mkdir(); (base / "done").mkdir()
        th.Thread(target=tr.serve_ask, daemon=True).start()
        for _ in range(50):
            if (base / "ask.sock").exists(): break
            time.sleep(0.05)
        def req(d, timeout=5):
            c = so.socket(so.AF_UNIX); c.settimeout(timeout); c.connect(str(base / "ask.sock"))
            c.sendall((json.dumps(d) + "\n").encode())
            try:
                return json.loads(c.makefile().readline())
            except so.timeout:
                return None
            finally:
                c.close()
        self.assertTrue(req({"op": "warm", "call": "c1"})["ok"])
        self.assertEqual(req({"op": "ask", "call": "c1", "question": "hi"})["answer"], "echo hi")
        self.assertEqual(tr.ASK_SESSIONS["c1"]["count"], 1)
        self.assertIsNone(req({"op": "ask", "call": "c1", "tid": "t9", "question": "slow q"}, timeout=0.3))
        for _ in range(60):
            if (base / "done" / "t9.json").exists(): break
            time.sleep(0.05)
        d = json.loads((base / "done" / "t9.json").read_text())
        self.assertEqual((d["spoken"], d["call_id"], d["callback"]), ("echo slow q", "c1", False))
        tr.ASK_SESSIONS["c1"]["count"] = tr.ASK_MAX_QUESTIONS
        old = tr.ASK_SESSIONS["c1"]["proc"]
        self.assertEqual(req({"op": "ask", "call": "c1", "question": "again"})["answer"], "echo again")
        self.assertIsNot(tr.ASK_SESSIONS["c1"]["proc"], old)  # fresh session after 10 questions
        self.assertTrue(req({"op": "end", "call": "c1"})["ok"])
        self.assertNotIn("c1", tr.ASK_SESSIONS)


class WatcherFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(watcher, n, v) for n, v in {
            "WATCHES": self.tmp / "watches", "EMAIL_QUEUE": self.tmp / "mail.jsonl",
            "WATCH_STATE": self.tmp / "w.json", "CALLS_LOG": self.tmp / "calls.jsonl",
            "telegram": lambda t: None, "quiet_now": lambda: False}.items()]
        for p in self.patches:
            p.start()
        (self.tmp / "watches").mkdir()
        (self.tmp / "mail.jsonl").write_text("")
        self.w = watcher.Watcher()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_reply_watch_triggers_call(self):
        (self.tmp / "watches" / "ab12.json").write_text(json.dumps(
            {"id": "ab12", "who": "Jordan", "about": "", "created": time.time(), "expires": time.time() + 999}))
        (self.tmp / "watches" / "old1.json").write_text(json.dumps(
            {"id": "old1", "who": "Bob", "about": "", "created": 0, "expires": time.time() - 1}))
        self.w.claude = object()
        seen = {}

        def fake_triage(mail, watches=None):
            seen["watches"] = watches
            return {"call": False, "watch": "ab12", "summary": "Jordan confirmed Tuesday"}
        self.w.triage = fake_triage
        with (self.tmp / "mail.jsonl").open("a") as f:
            f.write(json.dumps({"time": time.time(), "from": "Jordan <j@x.example.com>", "subject": "Re: times", "body": "Tue ok"}) + "\n")
        self.w.check_email()
        self.assertEqual(set(seen["watches"]), {"ab12"})          # expired watch dropped
        self.assertFalse((self.tmp / "watches" / "old1.json").exists())
        self.assertFalse((self.tmp / "watches" / "ab12.json").exists())  # fired once
        self.assertEqual(len(self.w.pending), 1)
        self.assertIn("Jordan", self.w.pending[0]["reason"])

    def test_job_reply_notifies(self):
        self.w.claude = object()
        self.w.triage = lambda mail, watches=None: {"call": False, "job_reply": True, "summary": "Acme wants a call"}
        sent = []
        with mock.patch.object(watcher, "notify", lambda lvl, t: sent.append((lvl, t))):
            with (self.tmp / "mail.jsonl").open("a") as f:
                f.write(json.dumps({"time": time.time(), "from": "HR <hr@acme.example>", "subject": "Re: application", "body": "x"}) + "\n")
            self.w.check_email()
        self.assertEqual(sent[0][0], "important")
        self.assertIn("Acme wants a call", sent[0][1])
        self.assertEqual(self.w.pending, [])

    def test_meeting_call_has_brief(self):
        now = dt.datetime.now(watcher.TZ).replace(microsecond=0)
        s = (now + dt.timedelta(minutes=5)).strftime("%Y%m%dT%H%M%S")
        e = (now + dt.timedelta(minutes=35)).strftime("%Y%m%dT%H%M%S")
        import icalendar
        self.w.cal = icalendar.Calendar.from_ical(
            f"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:m1\nSUMMARY:Call with Jordan\nDTSTART;TZID=America/New_York:{s}\n"
            f"DTEND;TZID=America/New_York:{e}\nATTENDEE:mailto:jordan@shop.example.com\nEND:VEVENT\nEND:VCALENDAR\n")
        self.w.cal_fetched = time.time()
        seen = {}
        def fake_run(args, **kw):
            seen["event"] = json.loads(args[args.index("--event") + 1])
            return mock.Mock(returncode=0, stdout="Jordan is the Acme recruiter; you owe her your portfolio.")
        with mock.patch.dict(os.environ, {"CALENDAR_ICS_URL": "x"}), mock.patch.object(watcher.subprocess, "run", fake_run):
            self.w.check_calendar()
        self.assertEqual(seen["event"]["attendees"], ["jordan@shop.example.com"])
        self.assertIn("owe her your portfolio", self.w.pending[0]["details"])

    def test_gone_room_marks_call_ended(self):
        self.w.in_call = {"in-live": time.time(), "in-stale": time.time()}
        class FakeLK:
            def __init__(s): s.room = s
            async def __aenter__(s): return s
            async def __aexit__(s, *a): return False
            async def list_rooms(s, req): return mock.Mock(rooms=[mock.Mock()] and [type("R", (), {"name": "in-live"})()])
        with mock.patch.object(watcher.api, "LiveKitAPI", FakeLK):
            asyncio.run(self.w.check_rooms())
        self.assertEqual(set(self.w.in_call), {"in-live"})
        last = json.loads((self.tmp / "calls.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["call_id"], last["event"]), ("in-stale", "ended"))

    def test_debrief_call_after_interview(self):
        now = dt.datetime.now(watcher.TZ).replace(microsecond=0)
        def ics(title, end_min_ago):
            s = (now - dt.timedelta(minutes=end_min_ago + 30)).strftime("%Y%m%dT%H%M%S")
            e = (now - dt.timedelta(minutes=end_min_ago)).strftime("%Y%m%dT%H%M%S")
            return (f"BEGIN:VEVENT\nUID:{title}\nSUMMARY:{title}\nDTSTART;TZID=America/New_York:{s}\n"
                    f"DTEND;TZID=America/New_York:{e}\nEND:VEVENT\n")
        cal = ("BEGIN:VCALENDAR\nVERSION:2.0\n" + ics("Interview with Acme", 6) + ics("Dentist", 6)
               + ics("Phone screen Acme", 60) + "END:VCALENDAR\n")
        import icalendar
        self.w.cal = icalendar.Calendar.from_ical(cal)
        self.w.check_debriefs(now)
        self.w.check_debriefs(now)  # no duplicates
        self.assertEqual(len(self.w.pending), 1)
        self.assertIn("Interview with Acme", self.w.pending[0]["reason"])
        self.assertIn("save_interview_debrief", self.w.pending[0]["details"])


class FakeSession:
    """Minimal AgentSession stand-in: event emitter + recorded generate_reply calls."""
    def __init__(self):
        self.handlers, self.said = {}, []

    def on(self, name, cb):
        self.handlers.setdefault(name, []).append(cb)

    def emit(self, name, **kw):
        for cb in self.handlers.get(name, []):
            cb(types.SimpleNamespace(**kw))


import types  # noqa: E402


class NeverGhost(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(agent, "CALLS_LOG", self.tmp / "calls.jsonl"), mock.patch.object(agent, "STATE", self.tmp),
                  mock.patch.object(agent.ReplyGuard, "REPLY_WAIT", 0.2), mock.patch.object(agent.ReplyGuard, "RESUME_WAIT", 0.2),
                  mock.patch.object(agent, "BUSY_UNTIL", [0.0])]
        for x in self.p:
            x.start()
        self.s = FakeSession()
        async def speak(text):
            self.s.said.append(text)
        self.g = agent.ReplyGuard(self.s, "call-x", speak)

    def tearDown(self):
        for x in self.p:
            x.stop()

    def run_for(self, seconds):
        async def go():
            t = asyncio.create_task(self.g.run())
            await asyncio.sleep(seconds)
            t.cancel()
        asyncio.run(go())

    def watchdog_events(self):
        f = self.tmp / "calls.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def test_dropped_generation_forces_a_reply(self):
        self.s.emit("user_state_changed", old_state="listening", new_state="speaking")
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.run_for(0.6)  # model never starts speaking
        self.assertTrue(self.s.said, "the owner was ignored")
        self.assertIn("Respond to the owner right now", self.s.said[0])
        ev = self.watchdog_events()[0]
        self.assertEqual((ev["event"], ev["cause"]), ("watchdog", "no reply after the owner spoke"))

    def test_no_fire_when_model_answers(self):
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.s.emit("agent_state_changed", old_state="listening", new_state="speaking")
        self.run_for(0.5)
        self.assertEqual(self.s.said, [])

    def test_still_silent_escalates_to_fixed_line_then_stops(self):
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.run_for(1.4)
        self.assertGreaterEqual(len(self.s.said), 2)
        self.assertEqual(self.s.said[1], "Say only: Sorry, say that again?")
        self.assertLessEqual(len(self.s.said), agent.ReplyGuard.MAX_FIRES)

    def test_cancelled_reply_is_resumed(self):
        self.s.emit("agent_state_changed", old_state="thinking", new_state="speaking")
        self.s.emit("conversation_item_added", item=types.SimpleNamespace(role="assistant", interrupted=True, text_content="I don't"))
        self.s.emit("agent_state_changed", old_state="speaking", new_state="listening")
        self.run_for(0.5)  # no real speech followed
        self.assertTrue(any("finish what you were saying" in t for t in self.s.said))
        self.assertEqual(self.watchdog_events()[0]["cause"], "reply cut off, owner didn't speak")

    def test_real_interruption_is_not_resumed(self):
        self.s.emit("conversation_item_added", item=types.SimpleNamespace(role="assistant", interrupted=True, text_content="I"))
        self.s.emit("user_state_changed", old_state="listening", new_state="speaking")
        self.run_for(0.5)  # owner is still talking
        self.assertEqual(self.s.said, [])

    def test_slow_but_coming_reply_is_not_doubled(self):
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.s.emit("speech_created", source="generate_reply")
        self.run_for(0.6)
        self.assertEqual(self.s.said, [])

    def test_generation_that_never_speaks_is_caught(self):
        with mock.patch.object(agent.ReplyGuard, "STUCK_THINKING", 0.3):
            self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
            self.s.emit("speech_created", source="generate_reply")
            self.run_for(0.9)
        self.assertTrue(self.s.said)

    def test_late_transcript_after_answer_does_not_refire(self):
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.s.emit("agent_state_changed", old_state="listening", new_state="speaking")
        self.s.emit("user_input_transcribed", is_final=True, transcript="Can you ask Claude how many jobs")
        self.s.emit("agent_state_changed", old_state="speaking", new_state="listening")
        self.run_for(0.6)
        self.assertEqual(self.s.said, [])

    def test_transcript_without_any_reply_still_fires(self):
        self.s.emit("user_input_transcribed", is_final=True, transcript="hello?")
        self.run_for(0.6)
        self.assertTrue(self.s.said)

    def test_fake_user_turn_around_agent_reply_is_ignored(self):
        # what the plugin emits for an agent reply after a tool: user speaking + agent speaking at once
        self.s.emit("user_state_changed", old_state="listening", new_state="speaking")
        self.s.emit("agent_state_changed", old_state="thinking", new_state="speaking")
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.s.emit("agent_state_changed", old_state="speaking", new_state="listening")
        self.run_for(0.6)
        self.assertEqual(self.s.said, [])

    def test_real_barge_in_then_silence_is_answered(self):
        self.s.emit("agent_state_changed", old_state="listening", new_state="speaking")
        time.sleep(0.3)
        self.s.emit("user_state_changed", old_state="listening", new_state="speaking")  # owner cuts in
        self.s.emit("agent_state_changed", old_state="speaking", new_state="listening")
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.run_for(0.6)
        self.assertTrue(self.s.said)

    def test_tool_return_without_speech_is_spoken(self):
        self.s.emit("function_tools_executed", function_calls=[])
        self.run_for(0.6)
        self.assertTrue(self.s.said)
        self.assertEqual(self.watchdog_events()[0]["cause"], "tool returned, nothing said")

    def test_waits_while_slow_tool_runs(self):
        agent.BUSY_UNTIL[0] = time.time() + 5
        self.s.emit("user_state_changed", old_state="speaking", new_state="listening")
        self.run_for(0.6)
        self.assertEqual(self.s.said, [])

    def test_model_error_apologises(self):
        self.s.emit("error", error="websocket closed", source=None)
        self.run_for(0.6)
        self.assertEqual(self.s.said[0], "Say only: Sorry, I lost you for a second. What were you saying?")
        self.assertTrue(self.watchdog_events()[0]["cause"].startswith("model error"))


class SoundPool(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for n in ("typing-a.ogg", "typing-b.ogg", "scifi-a.ogg", "pad-a.ogg", "pad-b.ogg", "chime-a.ogg", "notes.txt"):
            (self.tmp / n).write_bytes(b"x")
        self.p = mock.patch.object(agent, "SOUNDS", self.tmp)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_never_repeats_last_three(self):
        import random
        r = random.Random(1)
        recent = []
        for _ in range(200):
            f = agent.pick_sound(recent, rnd=r).name
            self.assertNotIn(f, recent[-3:])
            self.assertTrue(f.endswith(".ogg"))
            recent.append(f)
        self.assertEqual(len(set(recent)), 6)  # every clip gets used

    def test_hint_banned_and_off(self):
        import random
        r = random.Random(2)
        picks = [agent.pick_sound([], "scifi", r).name for _ in range(100)]
        self.assertGreater(picks.count("scifi-a.ogg"), 55)
        agent.save_sound_prefs({"liked": [], "banned": ["scifi-a.ogg"], "off": False})
        self.assertNotIn("scifi-a.ogg", [agent.pick_sound([], "scifi", r).name for _ in range(50)])

    def test_quick_tool_gets_no_sound_and_stop_fades(self):
        ts = agent.ThinkingSounds.__new__(agent.ThinkingSounds)
        ts.session = types.SimpleNamespace(agent_state="thinking")
        ts.current, ts.recent, ts.cache, ts.task, ts.volume = None, [], {}, None, 1.0
        played = []
        ts.player = types.SimpleNamespace(play=lambda cfg: played.append(cfg) or types.SimpleNamespace(stop=lambda: None))

        async def go():
            with mock.patch.object(agent.ThinkingSounds, "START_AFTER", 0.2):
                t = asyncio.create_task(ts.play_next())
                await asyncio.sleep(0.05)
                ts.session.agent_state = "speaking"  # quick tool: the answer came first
                await t
        asyncio.run(go())
        self.assertEqual(played, [])

    def test_fade_in_and_crossfade_out(self):
        import numpy as np
        ts = agent.ThinkingSounds.__new__(agent.ThinkingSounds)
        ts.volume = 1.0
        pcm = np.full(4800, 10000, dtype=np.int16)
        state = {"fade_out_at": None}

        async def collect(limit):
            out, gen = [], ts.frames(pcm, state)
            async for f in gen:
                out.append(np.frombuffer(f.data, dtype=np.int16).astype(int).max())
                if len(out) == 60:
                    state["fade_out_at"] = state["played"]
                if len(out) >= limit:
                    break
            return out
        levels = asyncio.run(collect(500))
        self.assertLess(levels[0], 1000)            # fades in
        self.assertEqual(levels[45], 10000)         # full level after 0.4 s
        self.assertLess(len(levels), 120)           # fades out and ends after ~0.4 s
        self.assertLess(levels[-1], 1000)


class SpeedUp(unittest.TestCase):
    def test_speeds_up_keeps_flow(self):
        import numpy as np
        from livekit import rtc
        from livekit.agents.voice import io as vio

        class Sink(vio.AudioOutput):
            def __init__(s):
                super().__init__(label="sink", capabilities=vio.AudioOutputCapabilities(pause=True))
                s.samples, s.flushed, s.cleared = 0, 0, 0
            async def capture_frame(s, f):
                await super().capture_frame(f); s.samples += f.samples_per_channel
            def flush(s):
                super().flush(); s.flushed += 1
            def clear_buffer(s):
                s.cleared += 1

        async def go(speed):
            sink = Sink()
            out = agent.SpeedOutput(sink, speed)
            t = np.arange(24000) / 24000
            tone = (np.sin(2 * np.pi * 180 * t) * 8000).astype(np.int16)
            for i in range(0, 24000, 480):
                await out.capture_frame(rtc.AudioFrame(tone[i:i+480].tobytes(), 24000, 1, 480))
            out.flush()
            await asyncio.sleep(0.05)
            out.clear_buffer()
            return sink
        s = asyncio.run(go(1.15))
        self.assertAlmostEqual(s.samples / 24000, 1 / 1.15, delta=0.03)
        self.assertEqual((s.flushed, s.cleared), (1, 1))
        s = asyncio.run(go(1.0))
        self.assertEqual(s.samples, 24000)  # 1.0 = untouched

    def test_speed_pref(self):
        with mock.patch.object(agent, "VOICE_PREFS", Path(tempfile.mkdtemp()) / "vp.json"):
            self.assertEqual(agent.speak_speed(), 1.15)
            agent.VOICE_PREFS.write_text('{"speed": 2}')
            self.assertEqual(agent.speak_speed(), 1.4)


class Greeting(unittest.TestCase):
    def test_uses_clip_then_falls_back(self):
        import numpy as np
        calls = []

        class S:
            async def say(self, text, audio=None):
                n = 0
                async for f in audio:
                    n += f.samples_per_channel
                calls.append(("say", text, n))

            async def generate_reply(self, instructions):
                calls.append(("model", instructions))
        tmp = Path(tempfile.mkdtemp()) / "g.ogg"
        tmp.write_bytes(b"x")
        with mock.patch.object(agent, "GREETING", tmp), \
             mock.patch.object(agent, "load_pcm", lambda p, rate=24000: np.zeros(24000, np.int16)):
            asyncio.run(agent.greet_inbound(S()))
        self.assertEqual(calls[-1], ("say", "Yes, sir? How may I help?", 24000))
        with mock.patch.object(agent, "GREETING", tmp.with_name("missing.ogg")):
            asyncio.run(agent.greet_inbound(S()))
        self.assertEqual(calls[-1], ("model", "Say only: Yes, sir? How may I help?"))


class InputStall(unittest.TestCase):
    def make(self):
        sess = FakeSession()
        sess.agent_state = "listening"
        meter = types.SimpleNamespace(last_read=time.time(), loud=[])
        meter.loud_seconds = lambda since: sum(d for t, d in meter.loud if t >= since)
        stalls = []
        async def on_stall(why):
            stalls.append(why)
        w = agent.StallWatch(sess, meter, "call-s", on_stall)
        return sess, meter, w, stalls

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(agent, "CALLS_LOG", self.tmp / "calls.jsonl"), mock.patch.object(agent, "STATE", self.tmp)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_owner_talking_but_model_deaf(self):
        sess, meter, w, stalls = self.make()
        now = time.time()
        w.last_activity = now - 15
        meter.loud = [(now - 6 + i * 0.02, 0.02) for i in range(250)]  # 5 s of loud audio, nothing heard for 15 s
        self.assertEqual(w.cause(now), "owner audible on the line but the model registered no speech")
        w.last_activity = now - 5  # a normal 5 s question: transcript arrives at the end
        self.assertIsNone(w.cause(now))

    def test_input_not_read(self):
        sess, meter, w, stalls = self.make()
        meter.last_read = time.time() - 5
        self.assertEqual(w.cause(time.time()), "audio input stopped being read")

    def test_no_false_alarm_when_heard_or_agent_talking(self):
        sess, meter, w, stalls = self.make()
        now = time.time()
        meter.loud = [(now - 6 + i * 0.02, 0.02) for i in range(250)]
        w.last_activity = now - 1  # model just noticed speech
        self.assertIsNone(w.cause(now))
        w.last_activity = now - 15
        sess.agent_state = "speaking"  # echo of the assistant itself
        self.assertIsNone(w.cause(now))

    def test_quiet_line_is_not_a_stall(self):
        sess, meter, w, stalls = self.make()
        w.last_activity = time.time() - 60
        self.assertIsNone(w.cause(time.time()))

    def test_run_fires_once_and_logs(self):
        sess, meter, w, stalls = self.make()
        meter.last_read = time.time() - 5
        with mock.patch.object(agent.StallWatch, "CHECK", 0.05):
            asyncio.run(asyncio.wait_for(w.run(), 2))
        self.assertEqual(stalls, ["audio input stopped being read"])
        ev = json.loads((self.tmp / "calls.jsonl").read_text().splitlines()[-1])
        self.assertEqual(ev["cause"], "input stalled: audio input stopped being read")

    def test_meter_survives_empty_denoiser_output(self):
        import numpy as np
        from livekit import rtc

        class FakeRN:
            def __init__(self, rate): self.n = 0
            def denoise_chunk(self, pcm):
                self.n += 1
                yield 0.5, np.zeros(0, np.float32)            # empty piece (resampler warm-up)
                yield 0.5, (pcm.astype(np.float32) / 32768)    # then the audio

        class Src:
            def __init__(s): s.i = 0
            async def __anext__(s):
                s.i += 1
                if s.i > 20: raise StopAsyncIteration
                return rtc.AudioFrame((np.ones(480, np.int16) * 5000).tobytes(), 24000, 1, 480)
            def on_attached(s): pass
            def on_detached(s): pass

        async def go():
            d = agent.DenoiseInput(Src())
            d.RNNoise = FakeRN
            n = 0
            try:
                while True:
                    await d.__anext__(); n += 1
            except StopAsyncIteration:
                pass
            return d, n
        d, n = asyncio.run(go())
        self.assertGreaterEqual(n, 19)
        self.assertGreater(d.loud_seconds(time.time() - 5), 0.3)


class StuckTurn(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(agent, "CALLS_LOG", self.tmp / "calls.jsonl"), mock.patch.object(agent, "STATE", self.tmp)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def make(self, live=True):
        sess = FakeSession()
        sess.agent_state = "listening"
        meter = types.SimpleNamespace(last_read=time.time(), loud=[])
        meter.loud_seconds = lambda since: sum(d for t, d in meter.loud if t >= since)
        ev = {"nudge": 0, "stall": []}
        async def nudge():
            ev["nudge"] += 1
        async def stall(why):
            ev["stall"].append(why)
        w = agent.StallWatch(sess, meter, "call-k", stall, nudge, lambda: live)
        return sess, meter, w, ev

    def test_turn_stuck_on_quiet_line_nudges_then_reconnects(self):
        sess, meter, w, ev = self.make()
        with mock.patch.object(agent.StallWatch, "STUCK_AFTER", 0.3), mock.patch.object(agent.StallWatch, "NUDGE_WAIT", 0.3), \
             mock.patch.object(agent.StallWatch, "CHECK", 0.05):
            sess.emit("user_state_changed", old_state="listening", new_state="speaking")
            w.last_final = time.time()
            asyncio.run(asyncio.wait_for(w.run(), 3))
        self.assertEqual(ev["nudge"], 1)
        self.assertEqual(ev["stall"], ["owner turn never ended even after a forced reply"])

    def test_really_talking_long_is_left_alone(self):
        sess, meter, w, ev = self.make()
        sess.emit("user_state_changed", old_state="listening", new_state="speaking")
        now = time.time()
        w.speaking_since, w.last_final = now - 30, now - 30
        meter.loud = [(now - 1, 0.5)]  # loud right now: they are still talking
        self.assertFalse(w.stuck(now))

    def test_nothing_after_hangup(self):
        sess, meter, w, ev = self.make(live=False)
        meter.last_read = time.time() - 10
        self.assertIsNone(w.cause(time.time()))
        w.speaking_since, w.last_final = time.time() - 30, time.time() - 30
        with mock.patch.object(agent.StallWatch, "CHECK", 0.05):
            async def go():
                t = asyncio.create_task(w.run()); await asyncio.sleep(0.3); t.cancel()
            asyncio.run(go())
        self.assertEqual((ev["nudge"], ev["stall"]), (0, []))


if __name__ == "__main__":
    unittest.main()
