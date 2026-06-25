-- VPN cert inventory snapshot. The OpenVPN agent ships the parsed cert
-- directory in each heartbeat (one entry per CA / server cert / client cert /
-- revoked cert / CRL). Stored as a JSONB column on vpn_status so the live
-- read-model has everything to render /vpn in one shot.

ALTER TABLE vpn_status
    ADD COLUMN IF NOT EXISTS certs JSONB;
