import os, sys, tempfile, time, unittest, importlib, json
d = tempfile.mkdtemp()
os.environ.update(VN_DIR=d, VN_CALLREQ=d, VN_IMESSAGE="/usr/bin/false")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vn_common as v
v.journal = lambda *a, **k: None
v.telegram = lambda t: True
daemon = importlib.import_module("voice-notify-daemon".replace("-", "_")) if False else None
import importlib.util
sp = importlib.util.spec_from_file_location("dm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice-notify-daemon.py"))
dm = importlib.util.module_from_spec(sp); sp.loader.exec_module(dm)


class T(unittest.TestCase):
    def setUp(self):
        self.c = v.db()
        for t in ("questions", "notifs", "inbound", "events", "kv", "chat"):
            self.c.execute(f"delete from {t}")

    def test_first_answer_wins(self):
        qid, new = v.q_add(self.c, "Send reply to Bob?", "approve", "gmail:abc")
        self.assertTrue(new)
        self.assertEqual(v.q_add(self.c, "again", "approve", "gmail:abc"), (qid, False))
        self.assertEqual(v.q_answer(self.c, qid, "imessage", "yes")[0], "ok")
        st, row = v.q_answer(self.c, qid, "telegram", "yes")
        self.assertEqual((st, row["answer_via"]), ("already", "imessage"))
        self.assertEqual(v.q_answer(self.c, "zzzz", "call", "x")[0], "missing")
        self.assertEqual(v.q_open(self.c), [])

    def test_self_close(self):
        qid, _ = v.q_add(self.c, "x", "check")
        self.assertTrue(v.q_self_close(self.c, qid, "sent mail"))
        self.assertFalse(v.q_self_close(self.c, qid, "again"))
        self.assertEqual(v.q_answer(self.c, qid, "call", "y")[0], "already")

    def test_quiet_hours(self):
        from datetime import datetime
        mk = lambda h: datetime(2026, 11, 4, h, 30, tzinfo=v.TZ).timestamp()
        self.assertTrue(v.quiet_now(mk(23)) and v.quiet_now(mk(3)))
        self.assertFalse(v.quiet_now(mk(7)) or v.quiet_now(mk(12)) or v.quiet_now(mk(22)))

    def test_info_falls_back_to_telegram_and_important_escalates(self):
        for lvl in ("info", "important"):
            self.c.execute("insert into notifs(id,level,text,created) values(?,?,?,?)", (lvl, lvl, "hello", time.time()))
        dm.handle_notifs(self.c)
        r = {x["id"]: x for x in self.c.execute("select * from notifs")}
        self.assertEqual(r["info"]["detail"], "telegram")
        self.assertIsNone(r["info"]["escalate_at"])
        self.assertIsNotNone(r["important"]["escalate_at"])
        self.c.execute("update notifs set escalate_at=?", (time.time() - 1,))
        dm.tick_escalations(self.c)
        self.assertTrue(os.path.exists(os.path.join(d, "vn-important.json")))
        self.assertFalse(os.path.exists(os.path.join(d, "vn-info.json")))

    def test_no_escalation_when_answered(self):
        qid, _ = v.q_add(self.c, "ok?", "approve")
        self.c.execute("insert into notifs(id,level,text,question_id,created) values('n9','important','ok?',?,?)", (qid, time.time()))
        dm.handle_notifs(self.c)
        v.q_answer(self.c, qid, "telegram", "yes")
        self.c.execute("update notifs set escalate_at=?", (time.time() - 1,))
        dm.tick_escalations(self.c)
        self.assertFalse(os.path.exists(os.path.join(d, "vn-n9.json")))

    def test_urgent_calls_and_caps(self):
        self.c.execute("insert into notifs(id,level,text,created) values('u1','urgent','fire',?)", (time.time(),))
        dm.handle_notifs(self.c)
        self.assertTrue(json.load(open(os.path.join(d, "vn-u1.json")))["urgent"])
        for _ in range(40): v.log_event(self.c, "text")
        self.c.execute("insert into notifs(id,level,text,created) values('i2','info','spam',?)", (time.time(),))
        dm.handle_notifs(self.c)
        self.assertEqual(self.c.execute("select status from notifs where id='i2'").fetchone()[0], "capped")

    def test_answered_question_notify_skipped(self):
        qid, _ = v.q_add(self.c, "q", "decide"); v.q_answer(self.c, qid, "call", "a")
        self.c.execute("insert into notifs(id,level,text,question_id,created) values('s1','important','q',?,?)", (qid, time.time()))
        dm.handle_notifs(self.c)
        self.assertEqual(self.c.execute("select status from notifs where id='s1'").fetchone()[0], "skipped")

    def test_check_schedule_stops_after_4h_and_waits_in_quiet(self):
        qid, _ = v.q_add(self.c, "q", "check")
        old = time.time() - 5 * 3600
        self.c.execute("update questions set created=?, next_check=? where id=?", (old, time.time() - 1, qid))
        dm.tick_checks(self.c)
        self.assertIsNone(self.c.execute("select next_check from questions where id=?", (qid,)).fetchone()[0])
        # nothing open -> no wake
        self.c.execute("update questions set status='answered'")
        from unittest import mock
        with mock.patch.object(dm.subprocess, "run", side_effect=AssertionError("woke Mac with nothing open")):
            dm.tick_checks(self.c)


class BrainGuard(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import brain
        self.b = brain

    def run_with(self, parts):
        from unittest import mock
        with mock.patch.object(self.b, "gemini", return_value={"ok": True, "ms": 1, "content": {"parts": parts}}):
            return self.b.run("turn it on", "", "", "", "", "", "caps")

    def test_claim_without_tool_becomes_delegation(self):
        reply, task, info = self.run_with([{"text": "Done. I turned on your morning briefing."}])
        self.assertEqual(reply, "On it, sir.")
        self.assertEqual(task, "turn it on")
        self.assertTrue(info["guarded"])

    def test_plain_answer_passes(self):
        reply, task, info = self.run_with([{"text": "It is 8:42 AM, sir."}])
        self.assertEqual((reply, task), ("It is 8:42 AM, sir.", None))

    def test_delegation_ack_is_neutral(self):
        from unittest import mock
        seq = [{"ok": True, "ms": 1, "content": {"parts": [{"text": "Claude will show you the draft first."}, {"functionCall": {"name": "delegate_to_claude", "args": {"task": "draft it"}}}]}},
               {"ok": True, "ms": 1, "content": {"parts": [{"text": "Right away."}]}}]
        with mock.patch.object(self.b, "gemini", side_effect=seq):
            reply, task, info = self.b.run("draft email", "", "", "", "", "", "caps")
        self.assertEqual((reply, task), ("On it, sir.", "draft it"))

    def test_clock_uses_agent_tz(self):
        from unittest import mock
        seen = {}
        def fake(system, *a, **k):
            seen["s"] = system; return {"ok": True, "ms": 1, "content": {"parts": [{"text": "ok"}]}}
        with mock.patch.object(self.b, "gemini", side_effect=fake):
            self.b.run("time?", "", "", "", "", "", "caps")
        from datetime import datetime; from zoneinfo import ZoneInfo
        self.assertIn(datetime.now(ZoneInfo(os.environ.get("AGENT_TZ", "UTC"))).strftime("%B %d"), seen["s"])

unittest.main()
