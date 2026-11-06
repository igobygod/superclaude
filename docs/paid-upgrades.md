# Paid upgrades (if you have a budget)

SuperClaude was built to run almost free. If you can spend money, these swaps make it faster, more reliable, or easier to set up.

**Before you buy, read this:**
- Only the options marked **Works today** run with this repo's code as it is. Every other row needs code changes that **nobody has built or tested yet**, and each row says what would change.
- Prices change. Each row links to the official pricing page. A dollar figure appears only where the vendor's own page states it (checked 2026-11-06).

## The upgrades

| Upgrade | What gets better | Cost | Status |
|---|---|---|---|
| **Claude Max plan** (instead of Pro) | More Claude work before you hit limits. The assistant shares your plan with your own Claude Code use, and the original build got close to its weekly limit. | Max 5x $100/month, Max 20x $200/month ([Anthropic help center](https://support.claude.com/en/articles/11049744-how-much-does-the-max-plan-cost)) | **Works today.** Sign in on the server with that account. |
| **Gemini API paid tier** (turn on billing for your key) | Higher rate limits, so fewer "429 / quota" errors. Those errors push texts to the slower Claude fallback. 503 "model busy" errors can still happen. | Pay per use ([Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)) | **Works today.** Same key, same code. Then raise the daily budgets in `gemini_chat_daemon.py` (300/day) and `gemini_daemon.py` (40/day). |
| **Your own domain name** | A tidy, permanent HTTPS address for the shortcuts and the dashboard. | Any registrar | **Works today.** Point it at the server and set `PUBLIC_HOST`. |
| **External uptime monitor** | Warns you when the *whole* server is down. The built-in health check can't, because it runs on the same server. | Many providers have paid plans | **Works today.** Monitor the HTTPS site from outside. |
| **Claude API key for email triage** | "Urgent email → phone call" | Pay per use ([Claude pricing](https://www.anthropic.com/pricing)) | **Works today.** It's optional: set `ANTHROPIC_API_KEY`. You also need your own mail sorter that fills `EMAIL_QUEUE`. |
| **A real phone number** (SIP trunk from [Twilio](https://docs.livekit.io/telephony/start/sip-trunk-setup.md) or [Telnyx](https://docs.livekit.io/telephony/start/providers/telnyx.md), or [LiveKit Phone Numbers](https://docs.livekit.io/telephony/start/phone-numbers.md)) | The assistant calls your **normal Phone app** from a real number, and you can call it from any phone. You don't need the Linphone app or its push setup. | Per number plus per minute (provider pricing pages) | **Not built.** livekit-sip supports provider trunks for both directions ([LiveKit telephony docs](https://docs.livekit.io/telephony.md)). You would create an outbound trunk to the provider, dial your phone number instead of a SIP address, and let only your number in on the inbound trunk. The Kamailio relay would no longer be needed. |
| **LiveKit Cloud** instead of self-hosted LiveKit | No Docker stack to run or babysit, and phone numbers and SIP are built in. LiveKit's docs say every Cloud plan includes one free US local number. | Free tier plus paid plans ([LiveKit pricing](https://livekit.com/pricing)) | **Not built.** Point `LIVEKIT_URL`, key and secret at your Cloud project and set up the trunk there. Then re-test the agent. |
| **A hosted iMessage API** (for example [Sendblue](https://www.sendblue.com), [Blooio](https://blooio.com), LoopMessage) | iMessage **without your own Mac**. No Tailscale, no Apple TV wake trick, no Full Disk Access. | Monthly per line (see each vendor; the prices they publish vary) | **Not built.** These companies run Apple hardware for you; Apple has no public iMessage API. You would replace the Mac listener and `imessage-send` with the vendor's webhook and API. Mac control (`mac-run`) would still need a Mac. |
| **A dedicated always-on Mac mini** | The Mac never sleeps, so you don't need the Apple TV wake trick. iMessage and Mac control are always instant, and your laptop stays yours. | Hardware purchase | **Works today**, with the same setup as in [07-mac.md](setup/07-mac.md) on that Mac. It can also host everything ([12-always-on-mac-host.md](setup/12-always-on-mac-host.md), untested). |
| **A paid cloud server** instead of the free one | Guaranteed capacity, and no risk of a free VM being reclaimed or unavailable in your region. | Any VPS with a public IPv4 and open UDP ports | **Works today.** The same setup steps work on any Ubuntu box. |

## Suggested budgets

- **A little:** Claude **Max 5x**, plus your own domain. This is the biggest win for the money, because Claude does all the real work.
- **More:** add the **Gemini paid tier** and an **uptime monitor** for speed and peace of mind.
- **Most:** add a **real phone number** (calls ring like normal calls) and either a **Mac mini** or a **hosted iMessage API**. Expect to build and test those code changes; see the "Not built" notes above.

## What paying doesn't fix
- The code guards (reply guard, stall watch, claim guard, read-back before sending) matter more than the model tier. Keep them.
- Narrowband audio causes mis-hearings, so keep **G722** on whatever phone path you use.
- Private facts stay on the Claude side, whatever you pay for.
