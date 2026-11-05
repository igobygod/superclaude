"""Place a call:  call.py "Interview with X in 10 minutes" [--details "..."]
Also:  call.py --setup-trunk   (create/refresh the Linphone outbound trunk)
"""

import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path

from livekit import api

STATE = Path(os.environ.get("VOICECALLER_STATE", "/var/lib/voicecaller"))


async def setup_trunk(lk: api.LiveKitAPI) -> None:
    server_user = os.environ["LINPHONE_SERVER_USER"]
    domain = os.environ.get("LINPHONE_DOMAIN", "sip.linphone.org")
    transport = getattr(api.SIPTransport, "SIP_TRANSPORT_" + os.environ.get("LINPHONE_TRANSPORT", "TCP"))
    info = api.SIPOutboundTrunkInfo(
        name="linphone",
        address=os.environ.get("LINPHONE_ADDRESS", domain),
        transport=transport,
        numbers=[server_user],
        auth_username=server_user,
        auth_password=os.environ["LINPHONE_SERVER_PASS"],
        from_host=domain,
        media_encryption=getattr(
            api.SIPMediaEncryption,
            "SIP_MEDIA_ENCRYPT_" + os.environ.get("LINPHONE_MEDIA_ENCRYPTION", "REQUIRE"),
        ),
    )
    for t in (await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())).items:
        if t.name == "linphone":
            await lk.sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id))
    trunk = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=info))
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "trunk_id").write_text(trunk.sip_trunk_id)
    print("trunk ready")


async def place_call(reason: str, details: str) -> str:
    call_id = "call-" + secrets.token_hex(4)
    async with api.LiveKitAPI() as lk:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="pa-caller",
                room=call_id,
                metadata=json.dumps({"reason": reason, "details": details, "call_id": call_id}),
            )
        )
    return call_id


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("reason", nargs="?")
    p.add_argument("--details", default="none")
    p.add_argument("--setup-trunk", action="store_true")
    a = p.parse_args()
    if a.setup_trunk:
        async with api.LiveKitAPI() as lk:
            await setup_trunk(lk)
        return
    if not a.reason:
        p.error("give a reason for the call")
    print(await place_call(a.reason, a.details))


if __name__ == "__main__":
    asyncio.run(main())
