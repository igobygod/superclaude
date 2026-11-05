#!/usr/bin/env python3
"""Render pronunciation options for a name in the live voice and send them to the owner on Telegram.

   pron_options.py NAME '["Jor-dan Lee", "Jor-den Lee", ...]'
The owner replies with a number on Telegram; the helper then saves that respelling to pronunciations.json
(pending choices are kept in /var/lib/voice-tasks/pron-options.json). Needs GEMINI_API_KEY + TELEGRAM_* in env.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from google import genai
from google.genai import types

MODEL = os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.8-live")
VOICE = os.environ.get("GEMINI_VOICE", "Puck")
PENDING = Path("/var/lib/voice-tasks/pron-options.json")


async def render(client, text: str) -> bytes:
    conf = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))),
        system_instruction="When asked to say a line, say exactly that line, clearly, nothing else.")
    pcm = bytearray()
    async with client.aio.live.connect(model=MODEL, config=conf) as s:
        await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text="Say this line: " + text)]),
                                    turn_complete=True)
        async for m in s.receive():
            sc = m.server_content
            if sc and sc.model_turn:
                for p in sc.model_turn.parts or []:
                    if p.inline_data:
                        pcm += p.inline_data.data
            if sc and sc.turn_complete:
                break
    return bytes(pcm)


def telegram(method: str, fields: dict, audio: tuple[str, bytes] | None = None) -> None:
    b = uuid.uuid4().hex
    body = b"".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in fields.items())
    if audio:
        body += (f"--{b}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{audio[0]}\"\r\n"
                 "Content-Type: audio/mpeg\r\n\r\n").encode() + audio[1] + b"\r\n"
    body += f"--{b}--\r\n".encode()
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"
    urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "multipart/form-data; boundary=" + b}), timeout=60)


async def main() -> None:
    name = sys.argv[1].strip()[:60]
    options = [o.strip()[:60] for o in json.loads(sys.argv[2]) if o.strip()][:5]
    if name not in options:
        options = [name] + options[:4]  # always include the plain spelling as a baseline
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    chat = os.environ["TELEGRAM_CHAT_ID"]
    telegram("sendMessage", {"chat_id": chat, "text": f"How should I say \"{name}\"? Listen and reply with the number "
                                                      f"(e.g. \"{name} 2\"). Same voice as your calls ({VOICE})."})
    for n, opt in enumerate(options, 1):
        pcm = await render(client, f"{opt}.")
        with tempfile.TemporaryDirectory() as d:
            raw, mp3 = Path(d, "a.pcm"), Path(d, "a.mp3")
            raw.write_bytes(pcm)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(raw),
                            "-b:a", "64k", str(mp3)], check=True)
            telegram("sendAudio", {"chat_id": chat, "title": f"{n}. {opt}", "performer": "Pronunciation",
                                   "caption": f"{n}. {opt}"}, (f"{n}.mp3", mp3.read_bytes()))
    pending = json.loads(PENDING.read_text()) if PENDING.exists() else {}
    pending[name] = {"options": options, "sent": time.time(), "voice": VOICE}
    tmp = PENDING.with_suffix(".tmp")
    tmp.write_text(json.dumps(pending))
    tmp.replace(PENDING)
    print("sent", name, options)


if __name__ == "__main__":
    asyncio.run(main())
