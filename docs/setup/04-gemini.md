# 4. Gemini API key

Gemini is the fast "front desk": it speaks on calls (Gemini Live) and answers most texts in a few seconds. Claude only gets the real work.

## Steps

1. **Create a Gemini API key** in Google AI Studio (free tier).
2. **Store it on the server only**, as `GEMINI_API_KEY` in `/etc/voice-caller/secrets.env` (root:voicecaller, mode 640).
   Why: only the `voicecaller` user can read it. The voice agent uses it directly. Text and video features never see the key: they talk to two small proxy services over Unix sockets (`voice-gemini-chat` and `voice-gemini`), which hold the key and strip it from any error message.
3. Restart `voice-caller`, `voice-gemini-chat` and `voice-gemini` (only when no call is live).

## Models used (as of the original build)

| Use | Model | Where to change |
|---|---|---|
| Phone calls (Gemini Live) | `gemini-3.8-live`, voice `Puck`, language `en-US` | `GEMINI_LIVE_MODEL`, `GEMINI_VOICE`, `VOICE_LANGUAGE` in the `voice-caller.service.d/model.conf` drop-in |
| Looking at pictures during a call | `gemini-3.8-flash` | `VISION_MODEL` |
| Text brain (iMessage, Ask Claude) | tried in order of real availability: `gemini-3-flash-preview`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.6-flash` | `CANDIDATES` in `server/lib/voice-notify/gemini_chat_daemon.py` |
| Video review and captions | flash `gemini-3.8-flash`, pro `gemini-3.1-pro-preview`, lite `gemini-3.5-flash-lite` | `MODELS` in `server/lib/voice-creator/gemini_daemon.py` |

Why `gemini-3.8-live`: the code's older default (a 2.5 native-audio model) took about 2.5 s to the first word; 3.8-live took about 0.6 to 1.0 s. Keep the `model.conf` drop-in, or the slower default comes back.

Notes from the build:
- `gemini-2.5-*` models returned 404 for newly created keys.
- `gemini-3.8-live` rejects "affective dialog" and a thinking budget (error 1007). Leave them off. "Proactive audio" is also off on purpose, because it lets the model decide not to answer.
- Model names change often. If you see 404s, check the current model list in AI Studio and update the names above.

## Free-tier limits and how the code copes

Google's free-tier limits change, so check them in AI Studio. The code adds its own limits so one feature never uses up the quota of another:

| Part | Own daily budget | What happens on errors |
|---|---|---|
| Text brain (`voice-gemini-chat`) | 300 requests/day; above 80% only one attempt per message | A model that fails is put on cooldown: **429** (quota) 15 min, or the delay Google asks for (1 min to 1 h); **503**/timeout 90 s; **404** 12 h. At most 2 attempts of about 2.5 s each (8 s with a picture), then the message goes to Claude. Never left unanswered. |
| Video helper (`voice-gemini`) | 40 requests/day | Retries 503 and falls back to other flash models. |
| Voice calls | Counted separately | Gemini Live has no rate setting; long outages show as a failed call. |

Check: `voice-gemini-status` (or `--json`) shows today's count, each model's cooldown and average speed.
