"""Create/refresh the livekit-sip INBOUND trunk + dispatch rule for owner calls
(relayed by voice-sip-relay / Kamailio from 127.0.0.1).

  inbound_setup.py                 # dispatch agent pa-caller (normal)
  inbound_setup.py --agent NAME    # dispatch another agent ("" = none, for tests)
  inbound_setup.py --extra-caller USER   # also allow USER (tests only)
  inbound_setup.py --show
Owned by the inbound session. Needs livekit.env + secrets.env in the environment.
"""
import argparse, asyncio, json, os
from livekit import api

NAME = "linphone-in"


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default="pa-caller")
    p.add_argument("--extra-caller", action="append", default=[])
    p.add_argument("--show", action="store_true")
    a = p.parse_args()
    async with api.LiveKitAPI() as lk:
        trunks = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        if a.show:
            for t in trunks:
                print("trunk", t.sip_trunk_id, t.name, list(t.numbers), list(t.allowed_addresses), list(t.allowed_numbers), t.media_encryption)
            for r in rules:
                print("rule", r.sip_dispatch_rule_id, r.name, list(r.trunk_ids), [(x.agent_name, x.metadata) for x in r.room_config.agents])
            return
        for r in rules:
            if r.name == NAME:
                await lk.sip.delete_dispatch_rule(api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=r.sip_dispatch_rule_id))
        for t in trunks:
            if t.name == NAME:
                await lk.sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id))
        trunk = await lk.sip.create_inbound_trunk(api.CreateSIPInboundTrunkRequest(trunk=api.SIPInboundTrunkInfo(
            name=NAME,
            numbers=[os.environ["LINPHONE_SERVER_USER"]],
            allowed_addresses=["127.0.0.1/32"],
            allowed_numbers=[os.environ["LINPHONE_PHONE_USER"], *a.extra_caller],
            media_encryption=api.SIPMediaEncryption.SIP_MEDIA_ENCRYPT_REQUIRE,
            max_call_duration=api.Duration(seconds=20 * 60) if hasattr(api, "Duration") else None,
        )))
        agents = []
        if a.agent:
            agents = [api.RoomAgentDispatch(agent_name=a.agent, metadata=json.dumps(
                {"inbound": True, "owner_initiated": True, "reason": "", "details": ""}))]
        rule = await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
            dispatch_rule=api.SIPDispatchRuleInfo(
                name=NAME,
                trunk_ids=[trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="in-")),
                room_config=api.RoomConfiguration(agents=agents),
            )))
        print("inbound ready", trunk.sip_trunk_id, rule.sip_dispatch_rule_id, "agent:", a.agent or "none")


asyncio.run(main())
