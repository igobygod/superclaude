#!/usr/bin/env python3
"""Build the runtime files for voice-sip-relay from /etc/voice-caller/secrets.env.
Writes /run/voice-sip-relay/{defs.cfg,db/uacreg,db/version}. Never prints secrets."""
import os, socket, shutil
from pathlib import Path

env = {}
for line in Path("/etc/voice-caller/secrets.env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
srv, pw, owner = env["LINPHONE_SERVER_USER"], env["LINPHONE_SERVER_PASS"], env["LINPHONE_PHONE_USER"]
# SERVER_PUBLIC_IP: this server's public IP; SERVER_PRIVATE_IP: its private/LAN IP (same as public if there is no NAT).
pub, priv = env["SERVER_PUBLIC_IP"], env.get("SERVER_PRIVATE_IP") or env["SERVER_PUBLIC_IP"]
for a in (pub, priv):
    assert all(c.isdigit() or c == "." for c in a), "bad IP"
for s in (srv, owner):
    assert s.replace("_", "").replace(".", "").replace("-", "").isalnum(), "bad user name"
assert ":" not in pw and "\n" not in pw, "password has a ':' (db_text separator)"

ips = set()
for h in ("sip.linphone.org", "sip11.linphone.org", "sip12.linphone.org"):
    try:
        ips.update(a[4][0] for a in socket.getaddrinfo(h, 5060, socket.AF_INET))
    except OSError:
        pass
if not ips:
    raise SystemExit("cannot resolve sip.linphone.org")

run = Path("/run/voice-sip-relay"); db = run / "db"
db.mkdir(parents=True, exist_ok=True)
(run / "defs.cfg").write_text(
    f'#!define OWNER_USER "{owner}"\n#!define SERVER_USER "{srv}"\n'
    f'#!define LINPHONE_NETS "{",".join(sorted(ips))}"\n'
    f'#!define PUBLIC_IP "{pub}"\n#!define CONTACT_ADDR "{pub}:5070"\n#!substdef "/PRIVATE_IP/{priv}/"\n')
cols = ("id(int,auto) l_uuid(string) l_username(string) l_domain(string) r_username(string) r_domain(string) "
        "realm(string,null) auth_username(string) auth_password(string) auth_ha1(string,null) auth_proxy(string) "
        "expires(int) flags(int) reg_delay(int) contact_addr(string) socket(string) ")
row = ":".join(["1", srv, srv, "sip.linphone.org", srv, "sip.linphone.org", "", srv, pw, "",
                "sip\\:sip.linphone.org;transport=tcp", "300", "0", "0", f"{pub}\\:5070",
                f"tcp\\:{priv}\\:5070"])
(db / "uacreg").write_text(cols + "\n" + row + "\n")
shutil.copy("/usr/share/kamailio/dbtext/kamailio/version", db / "version")
for p in (run, db, *db.iterdir(), run / "defs.cfg"):
    shutil.chown(p, "root", "kamailio")
    os.chmod(p, 0o770 if p == run else 0o750 if p.is_dir() else 0o640)
print(f"relay files ready ({len(ips)} Linphone IPs)")
