# 3. Linphone: two free SIP accounts

The calls use plain internet calling (SIP) through the free Linphone service, so there is no phone number and no phone bill.

## Why two accounts

| Account | Setting name | Who uses it | Why |
|---|---|---|---|
| **Phone account** | `OWNER_SIP_USER` (secret file: `LINPHONE_PHONE_USER`) | The Linphone app on your iPhone | This is "you". The relay only lets calls *from* this account reach the agent. |
| **Server account** | `SERVER_SIP_USER` (secret file: `LINPHONE_SERVER_USER`, password `LINPHONE_SERVER_PASS`) | The server | The server dials you *as* this account, and you dial *this* account to reach the agent. |

livekit-sip cannot register itself with a SIP provider, so the small Kamailio relay (`voice-sip-relay`) keeps the server account registered for incoming calls. For outgoing calls livekit-sip signs each call with the server account's password.

## Steps

1. **Create two free accounts** at Linphone's site (`sip.linphone.org`). Write down both user names and the server account's password.
2. **Put them in the server's secret file** `/etc/voice-caller/secrets.env`: `LINPHONE_PHONE_USER`, `LINPHONE_SERVER_USER`, `LINPHONE_SERVER_PASS` (optional: `LINPHONE_DOMAIN`, default `sip.linphone.org`).
3. **Install the Linphone app on the iPhone and sign in with the phone account.**
   Why: when the server calls, Linphone's push notification wakes the app and rings the phone even when it is locked. If the app is signed out, server calls fail with SIP **404**.
4. **Allow notifications for Linphone** when iOS asks.
   Why: push is how a locked phone rings. Assumption: Linphone's default push setting is on; the sources confirm that push rang the phone, not which switch controls it.
5. **Turn on encrypted media.** In Linphone settings, set media encryption to **SRTP**.
   Why: the server's trunk requires SRTP. With plain audio the call fails with SIP **488** (media encryption mismatch).
6. **Fix the codecs** (Linphone > Settings > Audio > Codecs):
   - **G722 ON** and above the others;
   - **PCMA and PCMU OFF** (or at least below G722).
   Why: PCMA/PCMU are 8 kHz "old phone line" audio. On those codecs Gemini misheard names and short words. G722 is wideband (HD) and fixed it. The original phone only offered opus, speex, PCMA and G729; livekit-sip skipped the others and chose PCMA until G722 was switched on. The first call after the change used G722.
   Check on the server after a call: `sudo docker logs voice-caller-sip-1 2>&1 | grep "using codecs" | tail -1` must say `G722/8000`.
7. **Add a contact named "Claude"** in Linphone (Contacts > + ), SIP address `sip:<SERVER_SIP_USER>@sip.linphone.org`.
   Why: tapping this contact calls the agent (an inbound call). You can then also say "call Claude" in Linphone. Assumption: Siri dialing through Linphone was never tested.

## How to turn inbound calls off

`sudo voice-inbound-setup --agent ""` (calls ring with no answer) or `sudo systemctl stop voice-sip-relay` (the server account goes offline).

## Common errors

| SIP code | Meaning here |
|---|---|
| 404 | The iPhone app is not signed in. Open Linphone. |
| 488 | Encryption mismatch. Set SRTP in the app; the trunk must use `SIP_MEDIA_ENCRYPT_REQUIRE`. |
| 486 | You declined or hung up the call. Not a server fault. |
| 403 (in the relay log) | A caller that is not your phone account, or not from Linphone's servers, was blocked. That is on purpose. |
