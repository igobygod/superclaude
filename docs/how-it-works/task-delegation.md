# Task delegation: handing real work to Claude

Gemini answers fast but does no real work. Anything that needs email, files, the web, the Mac or thinking goes to **headless Claude Code** through a queue. The runner is `server/lib/voice-tasks/task_runner.py` (`voice-tasks.service`, user `claude-helper`).

## The queue

1. A tool (the voice agent's `give_task_to_claude`, the text brain's `delegate_to_claude`) or Telegram writes a JSON file into `/var/lib/voice-tasks/queue/`.
2. The runner picks it up (max **2 tasks at once**), moves it to `running/`, and runs it by **kind**:

   | Kind | Runs |
   |---|---|
   | `claude` (default) | headless Claude on the server |
   | `imessage` | `imessage-send` through the Mac |
   | `mac`, `mac_resume` | `mac-run` (new or resumed Claude session on the Mac) |
   | `mac_sessions`, `mac_running`, `mac_agents`, `mac_message`, `mac_look` | read Mac session lists, message a session, take a screen look |

3. Each task runs in its own process group (so it can be killed cleanly), with a **45-minute timeout**.
4. The result is written to `jobs/voice-<id>.md` (full text) and `done/<id>.json`, which includes a short **SPOKEN** line for the voice to read out.
5. The runner records usage (`voice-usage record`) and journals the task to memory.
6. If no call announced it, `voice-watcher` calls you back (or the text side texts you).

## How Claude is started

- Cold start: `claude -p --model sonnet|opus --permission-mode auto` in `~claude-helper/assistant`, with the voice rules and the job path in the message.
- **Warm spare:** to save start-up time, one Sonnet Claude is pre-started (stream-json input) and waits. It is used for exactly **one** task and then replaced, so tasks never share context. It is rotated after 20 minutes idle (`WARM_SPARE` can turn it off).
- Confirmed sends and Opus tasks always start cold.
- "Clearly local" tasks (job files, notes, server files) start cold with `--strict-mcp-config` and no connectors, which is faster.

## Sending safety

- Gmail **send/reply** tools are added (`--allowedTools ...send_message ...reply`) only when the task is marked `confirmed`, which only happens after a read-back and your yes.
- If Claude tried to send and was denied (`permission_denials`), the result is turned into "blocked, not sent".
- A 30-minute duplicate rule blocks accidental double sends, unless the task says you explicitly asked to send it again.

## ask_claude: fast answers during a call

For questions (not jobs) the agent uses `ask_claude`, served by the runner on the Unix socket `/var/lib/voice-tasks/ask.sock` (ops `warm`, `ask`, `end`):
- When a call is answered, one **warm** Sonnet stream-json session starts for that call: read-only, send tools disallowed, recent jobs preloaded, answers in at most 3 spoken sentences.
- It is refreshed after 10 questions or 150K tokens, and closed when the call ends, after 25 minutes idle, or on STOP.
- The tool waits up to 25 s (`ASK_WAIT`). A later answer arrives as a finished task and is announced. If the socket is missing it queues a normal task.
- Typical answer: about 6.4 s.

## Kill switch

Create `/var/lib/voice-tasks/STOP` (or say "stop everything", or `agent-stop`, or the dashboard's Stop all):
- running tasks' process groups are killed, the queue is cancelled, no callbacks are made, no new task starts;
- an "ask" blocked by STOP still writes a `done/<id>.json` saying "Cancelled", so nothing hangs.
Remove the file (`agent-resume`, "resume tasks") to continue.
