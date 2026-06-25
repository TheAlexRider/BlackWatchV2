# OpenVPN box — incident notes + operator reference

EC2: `52.9.243.84` (private: `172.16.1.97`) · OS: Amazon Linux 2 · systemd 219
Unit: `openvpn-server@server.service` (the *new* unit — see "legacy paths" below)

---

## What happened on 2026-06-04 → 06-05

VPN suddenly stopped accepting connections for everyone. Three independent
problems stacked on top of each other, all surfaced at once when sessions
expired and clients reconnected:

### Problem 1 — `firewalld` had dropped UDP/49491 (universal block)

After the most recent reboot, the `public` zone's permanent config didn't
include UDP/49491. Active firewalld zone showed:

```
services: ssh dhcpv6-client
ports: (empty)
```

Result: every UDP packet bound for `:49491` walked past INPUT rules 1–7
without matching and hit the firewalld default `REJECT ... icmp-host-prohibited`
at the bottom. `tcpdump` saw the packets at the NIC; OpenVPN never did.

**Fix (one-shot, permanent across reboots):**
```bash
sudo firewall-cmd --add-port=49491/udp --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports                # should now show: 49491/udp
```

### Problem 2 — server cert expired

After the firewall was opened, TLS handshakes were now reaching the server,
and every client got:

```
OpenSSL: error:14094415:SSL routines:ssl3_read_bytes:sslv3 alert certificate expired
```

That alert is the **client** rejecting the server's cert. The server cert's
`notAfter` was `Jun 4 18:00:19 2026 GMT` — it expired a few hours before the
incident. Existing sessions stayed up because OpenVPN doesn't re-verify the
cert on live tunnels; new connections (after the reboot) all failed.

**Fix — renew the same cert under the same name:**
```bash
cd /etc/openvpn/easy-rsa
sudo EASYRSA_BATCH=1 ./easyrsa renew server_er1BTQWVqDrnWXNs nopass
sudo cp pki/issued/server_er1BTQWVqDrnWXNs.crt /etc/openvpn/server/server_er1BTQWVqDrnWXNs.crt
sudo systemctl restart openvpn-server@server.service

# verify
sudo openssl x509 -in /etc/openvpn/server/server_er1BTQWVqDrnWXNs.crt -noout -dates
```

If `easyrsa renew` errors with "must revoke first" (older easyrsa), fallback:
```bash
cd /etc/openvpn/easy-rsa
sudo ./easyrsa --batch rm-cert server_er1BTQWVqDrnWXNs
sudo EASYRSA_BATCH=1 EASYRSA_REQ_CN=server_er1BTQWVqDrnWXNs ./easyrsa build-server-full server_er1BTQWVqDrnWXNs nopass
sudo cp pki/issued/server_er1BTQWVqDrnWXNs.crt /etc/openvpn/server/server_er1BTQWVqDrnWXNs.crt
sudo cp pki/private/server_er1BTQWVqDrnWXNs.key /etc/openvpn/server/server_er1BTQWVqDrnWXNs.key
sudo chown root:root /etc/openvpn/server/server_er1BTQWVqDrnWXNs.{crt,key}
sudo chmod 600 /etc/openvpn/server/server_er1BTQWVqDrnWXNs.key
sudo systemctl restart openvpn-server@server.service
```

Clients don't need to update their `.ovpn` profiles — the **CA** didn't change,
only the server cert was re-signed by the same CA.

### Problem 3 — `WARNING: Failed to stat CRL file` (latent, observed during diagnosis)

After OpenVPN drops privileges to `user nobody / group nobody`, `nobody`
couldn't `stat` `/etc/openvpn/server/crl.pem` due to permissions. Non-fatal
(connections still work without CRL re-load) but means revoked users wouldn't
be re-blocked after a CRL update.

**Fix:**
```bash
sudo chmod 644 /etc/openvpn/server/crl.pem
sudo systemctl restart openvpn-server@server.service
```

---

## Operator reference — paths & commands

### Systemd unit (the one in use)
- Unit:       `openvpn-server@server.service`
- Definition: `/usr/lib/systemd/system/openvpn-server@.service`
- Drop-in:    `/etc/systemd/system/openvpn-server@server.service.d/override.conf`
              (currently sets `ProtectHome=no` so PAM Google Authenticator can read each user's `~/.google_authenticator`)
- Working dir: `/etc/openvpn/server/` (relative paths in `server.conf` resolve from here)

### Config + cert paths (NEW unit — these are the live ones)
- Config:           `/etc/openvpn/server/server.conf`
- CA cert:          `/etc/openvpn/server/ca.crt`
- Server cert:      `/etc/openvpn/server/server_er1BTQWVqDrnWXNs.crt`
- Server key:       `/etc/openvpn/server/server_er1BTQWVqDrnWXNs.key`
- TLS-crypt key:    `/etc/openvpn/server/tls-crypt.key`
- CRL:              `/etc/openvpn/server/crl.pem`
- Live status:      `/run/openvpn-server/status-server.log`
- Pool-persist:     `/etc/openvpn/server/ipp.txt` (user → assigned virtual IP, persisted across restarts)

### Legacy paths (OLD unit `openvpn@server` — should not be in use)
- Config:    `/etc/openvpn/server.conf` (delete or rename to avoid confusion)
- Cert:      `/etc/openvpn/server_er1BTQWVqDrnWXNs.crt` (duplicate of the live one — stale)
- CA:        `/etc/openvpn/ca.crt` (duplicate)
- Status:    `/var/log/openvpn/status.log` (gets written if old unit ever started; otherwise stale)
- **Disable the old unit so it can never compete:**
  ```bash
  sudo systemctl stop openvpn@server.service 2>/dev/null
  sudo systemctl disable openvpn@server.service 2>/dev/null
  ```

### Easy-RSA PKI
- Root:            `/etc/openvpn/easy-rsa/`
- CA cert (truth): `/etc/openvpn/easy-rsa/pki/ca.crt`
- Issued certs:    `/etc/openvpn/easy-rsa/pki/issued/<name>.crt`
- Private keys:    `/etc/openvpn/easy-rsa/pki/private/<name>.key`
- Revoked:         `/etc/openvpn/easy-rsa/pki/revoked/certs_by_serial/`
- CRL (truth):     `/etc/openvpn/easy-rsa/pki/crl.pem`

### Client packages (distributed `.ovpn` bundles)
- `/etc/openvpn/client-packages/<username>/`
  - `<username>.crt`, `<username>.key`, `ca.crt`, plus the `.ovpn` config

### Logs
| What | Where | How to read |
|---|---|---|
| OpenVPN service log | systemd journal, unit `openvpn-server@server` | `sudo journalctl -u openvpn-server@server -f` |
| Live status (connected clients) | `/run/openvpn-server/status-server.log` | `sudo cat /run/openvpn-server/status-server.log` |
| BlackWatch VPN agent | systemd journal, unit `blackwatch-vpn-agent` | `sudo journalctl -u blackwatch-vpn-agent -f` |
| BlackWatch EC2 agent (this box) | systemd journal, unit `blackwatch-agent` | `sudo journalctl -u blackwatch-agent -f` |
| iptables drops (kernel) | `dmesg` or `/var/log/messages` | `sudo dmesg | tail -50` |

---
xx## Diagnostic playbook (next incident)

Run these in order. The first command that gives a result that isn't "fine"
points at the layer where the break is.

```bash
# 1. Is the service actually up?
sudo systemctl status openvpn-server@server.service --no-pager | head -8

# 2. Are clients' UDP packets reaching the NIC?
sudo tcpdump -i any -n udp port 49491 -c 5 -nn   # ~5s, have someone try to connect

# 3. Is firewalld blocking?
sudo firewall-cmd --list-ports                    # must include 49491/udp
sudo iptables -L INPUT -n --line-numbers

# 4. Does the server cert / CA / CRL look healthy?
sudo openssl x509 -in /etc/openvpn/server/server_er1BTQWVqDrnWXNs.crt -noout -dates -subject -issuer
sudo openssl x509 -in /etc/openvpn/server/ca.crt -noout -dates
sudo openssl crl  -in /etc/openvpn/server/crl.pem -noout -lastupdate -nextupdate

# 5. The actual error during a failed connection
sudo journalctl -u openvpn-server@server -f
# In another terminal have a user try to connect; the line starting with
# "VERIFY ERROR", "TLS Error:", "OpenSSL: error", or "AUTH_FAILED" tells you.

# 6. Per-IP block (fail2ban)?
sudo fail2ban-client status
sudo fail2ban-client status sshd 2>/dev/null
sudo fail2ban-client status openvpn 2>/dev/null
sudo fail2ban-client set <jail> unbanip <ip>      # to release if needed

# 7. Are there TWO openvpn processes (legacy + new) competing?
ps -eo pid,etime,user,comm,args | grep openvpn | grep -v grep
sudo ss -ulnp | grep openvpn
```

### Mapping symptoms to causes

| Symptom | Likely layer | First fix |
|---|---|---|
| "Connection failed to establish within given time" | network/firewall | step 2 + 3 — firewalld port |
| Server journal silent during connect (tcpdump sees packets) | firewalld/iptables | step 3 — open the port |
| `TLS Error: TLS handshake failed` + `certificate expired` | expired server cert | step 4 → renew via Problem 2 above |
| `VERIFY ERROR: depth=0` for ONE user | their client cert | reissue that user's package |
| `AUTH_FAILED` in journal | PAM / Google Authenticator | check `~<user>/.google_authenticator`, check `ProtectHome=no` override still present |
| Single user's IP being dropped | fail2ban | step 6 — `unbanip` |
| Nothing in journal for *anyone*, even with tcpdump packets | something between NIC and openvpn (rare) | check `ps`/`ss` for which process actually owns the port |

---

## Latent issues to address (non-urgent)

1. **Duplicate cert/CA files** in `/etc/openvpn/` (legacy unit's working dir) vs
   `/etc/openvpn/server/` (new unit's). The legacy unit is disabled but the
   files remain — confusing during diagnosis. Cleanup:
   ```bash
   sudo mv /etc/openvpn/server.conf /etc/openvpn/server.conf.legacy 2>/dev/null
   sudo mv /etc/openvpn/server_er1BTQWVqDrnWXNs.crt /etc/openvpn/server_er1BTQWVqDrnWXNs.crt.legacy 2>/dev/null
   sudo mv /etc/openvpn/ca.crt /etc/openvpn/ca.crt.legacy 2>/dev/null
   ```
2. **Cert expiry monitoring in BlackWatch** — the OpenVPN backlog (Tier 1 #1)
   has this planned: periodic `openssl x509 -noout -enddate` on server cert
   + CA + CRL; emit `vpn.cert.expiring` at T-30 / T-7 / T-1 days. Build this
   so a future expiration produces a warning, not an outage.
3. **firewalld persistence audit** — confirm any other ports the box needs
   (BlackWatch agent SQS callbacks etc.) are added with `--permanent` so they
   survive reboots:
   ```bash
   sudo firewall-cmd --list-all
   ```
4. **Disable the legacy `openvpn@server.service`** (see "Legacy paths" above)
   so it can't ever boot up alongside the new unit.
