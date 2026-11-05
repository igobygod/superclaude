# 8. A separate Apple ID for the agent

You text the agent like a person. For that it needs its **own** iMessage address.

## Why not use your own Apple ID

The first version signed the Mac's Messages in as the owner's own Apple ID, and sent replies to the owner's own number. Apple treats that as a "chat with yourself":
- every text showed up **twice** in the Messages database (`chat.db`), so the listener forwarded it twice and a "Yes" could run an action twice;
- your own texts came back to the iPhone as grey echo bubbles.

De-duplicating the two rows helped, but the real fix was a **separate Apple ID** for the agent. After the switch: one row per message, no echo, one reply per text.

## Steps

1. **Create a new free Apple ID** for the agent (any email you control). Below it's called `AGENT_APPLE_ID`. No setting reads it: the Mac simply sends from its first enabled iMessage account, so that account must be this one.
2. **On the Mac, sign Messages in with the agent's Apple ID**, and make it the **only enabled** iMessage account (sign your own Apple ID out of Messages on that Mac).
   Why: `imessage-send-mac` sends from the **first enabled** iMessage account. If none is signed in it fails with an error, and the server falls back to Telegram instead of crashing.
3. **On your iPhone, save a contact named "Claude"** with the agent's Apple ID address, and text it.
4. **Tell the server how to recognise you.** Set `OWNER_PHONE` and `OWNER_EMAIL` (and `OWNER_HANDLES` if you have more). The listener only forwards **one-to-one** chats from those handles. Everything else in Messages is ignored.

## Check

- Send "hi" to the "Claude" contact. You should get one reply and no grey echo.
- On the Mac, `~/.imessage-agent/sent.log` contains only the agent's replies.
