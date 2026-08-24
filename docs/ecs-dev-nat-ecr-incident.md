# ECS Development ECR Connectivity Incident

**Date:** August 22–24, 2026  
**Instance:** `i-08ba075aeb40c50af`  
**Private IP:** `172.17.1.113`  
**Environment:** Development

## Symptom

ECS tasks could not pull registry authentication from Amazon ECR:

```text
TaskFailedToStartResourceInitializationError
ECR GetAuthorizationToken: i/o timeout
```

SSM and the BlackWatch agent also stopped working on the development NAT instance.

## Root Cause

The development NAT instance experienced severe memory exhaustion. It is a `t4g.nano` instance with very limited memory and no swap. The kernel repeatedly reported OOM events and killed `yum` processes.

The key event occurred on August 22 at approximately 09:59 UTC / 15:29 IST:

```text
Out of memory: Killed process 23881 (yum)
```

After the host became unstable, access to the EC2 Instance Metadata Service (`169.254.169.254`) failed with:

```text
network is unreachable
```

This caused failures in SSM, `ec2net`, and the BlackWatch agent. NAT/ECR connectivity also became unreliable.

## Why Reboot Fixed It

Rebooting the instance:

- cleared the memory and process state;
- recreated the ENI and link-local metadata route;
- restarted the networking services and agents;
- restored NAT connectivity.

The reboot did not fix a missing iptables rule. The required Dev NAT rule was already saved:

```text
172.17.0.0/16 -> MASQUERADE via eth0
```

## Evidence

- `eth0` had no RX/TX errors after reboot.
- `INPUT` and `OUTPUT` firewall policies were `ACCEPT`.
- Conntrack usage was low: `175 / 14336`.
- Direct access to `https://api.ecr.us-west-1.amazonaws.com` returned HTTP `404`, confirming post-reboot connectivity.
- The instance had repeated OOM events before the incident.

## Prevention

- Move the NAT instance to a larger instance type.
- Add swap or zram as an interim safeguard.
- Monitor memory, OOM events, IMDS reachability, and ECR connectivity.
- Investigate and control recurring `yum`/`update-motd` jobs.
- Consider replacing the NAT instance with a managed NAT Gateway or adding a resilient alternative.

## Note

The exact kernel-level reason why IMDS became unreachable after the OOM event was not directly recorded. Memory exhaustion is the strongest confirmed cause and the reboot restored the affected host state.
