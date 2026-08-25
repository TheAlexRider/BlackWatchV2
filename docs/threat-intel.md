# Threat-intel enrichment

Every event with an IP observable is enriched at ingest with country, ASN, and
threat-feed tags. Data lives in `intel.db` (separate from the events DB) so
feed refreshes never contend with the hot events path.

## Feeds

Local-lookup only. No paid APIs. No per-event calls.

| Feed | URL |
|---|---|
| `spamhaus_drop` | https://www.spamhaus.org/drop/drop.txt |
| `spamhaus_edrop` | https://www.spamhaus.org/drop/edrop.txt |
| `firehol_level1` | https://iplists.firehol.org/files/firehol_level1.netset |
| `tor_exit` | https://check.torproject.org/torbulkexitlist |

## GeoIP / ASN

Uses MaxMind GeoLite2-Country and GeoLite2-ASN MMDBs.

Set the licence key:

```
export MAXMIND_LICENSE_KEY=xxxxxxxxxxxxxxxx
```

If unset, GeoIP is silently skipped (logged once) — enrichment still runs and
feed matching continues to work.

## Storage

- `intel.db`  ~5-15 MB
- `GeoLite2-Country.mmdb`  ~5 MB
- `GeoLite2-ASN.mmdb`  ~10 MB

Location: `$BLACKWATCH_DATA_DIR` (default: current working directory).

## Force a refresh

```
python -m blackwatch.intel.refresher
```

The connector scheduler also triggers a refresh once per 24h automatically.

## Enriched shape

Stored on `event.extra.intel`:

```
{
  "country": "US",
  "asn": 15169,
  "asn_org": "Google LLC",
  "feeds": ["spamhaus_drop"],
  "is_tor": false,
  "is_bogon": false
}
```

## Read status

`GET /api/intel/status` returns per-feed `last_success`, `last_status`, and
`entries` counts.

## On-demand IP intelligence

The Tools → IP lookup page keeps the no-key path as its default. It uses the
existing `ip-api.com` fast lookup, local feed matches, reverse DNS, observed
BlackWatch events, and certificate-transparency pivots when a reverse-DNS
domain is available. Optional provider failures and quotas never hide those
results.

The optional provider keys are server-only environment variables:

| Provider | Account / key page | Environment variable | Notes |
|---|---|---|---|
| GreyNoise Community | https://viz.greynoise.io/ | `GREYNOISE_API_KEY` | Anonymous Community lookups may work with a limited quota. |
| AbuseIPDB | https://www.abuseipdb.com/register | `ABUSEIPDB_API_KEY` | Free account checks are quota-limited. |
| VirusTotal | https://www.virustotal.com/gui/join-us | `VIRUSTOTAL_API_KEY` | Public API use is account-, quota-, and terms-limited. |

For Docker Compose, copy `.env.example` to `.env`, add only the keys you
choose, and rebuild/restart the `ui` service. Never paste keys into the
browser, `NEXT_PUBLIC_*` variables, event payloads, or the database. The UI
labels every provider as available, optional, rate-limited, or unavailable so
an operator can tell exactly what contributed to a result.
