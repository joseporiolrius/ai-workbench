# DNS and HTTPS operations for S10–S14

The workbench probe targets `https://wb.aNNN.dbai24.i40sys.com/` with the
existing basic-auth Secret. It requires TLS, verifies the hostname and chain,
accepts only 2xx, and does not follow redirects. HTTP, an untrusted certificate
and a 401 are failures. Never fix a probe with `insecure_skip_verify: true`.

Use these panels alongside the existing Qdrant and golden-signal panels:

| Question | Query or evidence | Interpretation |
|---|---|---|
| Can the user reach the authenticated application? | `probe_success{job="workbench-probe"}` | 1 only after DNS, TLS, auth and application all succeed |
| Is the exporter being scraped? | `up{job="workbench-probe"}` | 1 alone does not mean the application works |
| Did the server reject auth or fail? | `probe_http_status_code{job="workbench-probe"}` | 401: check the paired credentials; 404/5xx: inspect Ingress/endpoints/pods |
| Did HTTPS negotiate? | `probe_http_ssl{job="workbench-probe"}` | 1 proves TLS was used; combine with probe success for verification |
| How long until the served certificate expires? | `(probe_ssl_earliest_cert_expiry{job="workbench-probe"} - time()) / 86400` | Investigate below 14 days; never force an issuance to test a panel |
| Is the managed certificate ready? | `certmanager_certificate_ready_status{job="cert-manager",namespace="workbench",condition="True"}` | 0: ask the instructor to inspect Certificate, Issuer and events |
| Has renewal been due for more than a day? | `time() - certmanager_certificate_renewal_timestamp_seconds{job="cert-manager",namespace="workbench"}` | Above 86400: inspect renewal errors and the issuance ledger |
| Is the controller observable? | `up{job="cert-manager"}` | 0: controller or scrape failure, not proof of a bad certificate |

The supplied expiry, readiness, renewal-overdue and controller alerts complement
`WorkbenchDown`. Prometheus displays them but has **no notification route**;
`severity` is a label, not a delivered page. Students do not add Alertmanager.

## Diagnose without spending certificate quota

1. Check the assigned A record against the retained Elastic IP. The instructor
   queries both `dns1.dbai24.i40sys.com` and `dns2.dbai24.i40sys.com` directly,
   over UDP and TCP, for the parent and affected child SOA/NS. Compare serials
   and delegation with the registered assignment. A recursive answer alone can
   be cached and does not prove both authorities work.
2. Inspect TLS validity, hostname and chain. A staging certificate is intentionally
   untrusted by normal browsers. An expired or wrong-host certificate is a TLS
   failure; do not rotate basic-auth, delete Secrets or request a new certificate
   as a diagnostic step.
3. If TLS succeeds and the response is 401, compare the paired ingress/probe
   credential procedure. A password rotation can take about a minute to reach
   the mounted Secret. Keep password values out of logs and screenshots.
4. If auth succeeds but the backend is absent, inspect deployment replicas,
   endpoints and application logs. Qdrant `/metrics` remains cluster-internal on
   port 6333 and is independent of the public TLS path.

## Shared service incidents and escalation

Oriol Rius owns the shared DNS service and identity/ACME operations. The instructor
running the session receives student reports, confirms scope and escalates shared
failures to Oriol. Use the course's existing incident channel; include the time,
affected assigned hostname, failing layer and sanitized evidence. Never send TSIG,
passwords, tokens or private keys. Email requires the operator's approval.

| Incident | Operator action | Student/course response |
|---|---|---|
| Primary unavailable, secondary answering | Oriol checks k5 container/network; verifies k6 authoritative answers and the latest successful backup | Preserve workload; pause DNS writes and issuance, use already valid services |
| Secondary stale or unavailable | Oriol compares SOA serials after the 60-second refresh interval, checks NOTIFY/TSIG/transfer logs and TCP/UDP53; escalate if still stale after two intervals | Do not force issuance while authority answers disagree |
| Broken parent/child delegation | Oriol compares registered NS with parent and both child authorities; restore only owned records | Preserve addresses and assignments; do not create another namespace or account |
| Expiry, not-Ready or overdue renewal | Instructor inspects cert-manager events and DNS, then Oriol checks the private issuance reservation and any Retry-After | Do not force production renewal, recreate the ACME account or retry through a 429 |
| Backup older than 15 minutes | Oriol runs `/opt/plakar/check-dbai24-dns-backup.py` on k5/k6 and checks the dedicated timer | Hold enrollment/destructive recovery until a fresh encrypted checkpoint exists |

The instructor reviews shared-primary/secondary observation and backup freshness
before class and while diagnosing an incident. These checks do not send automatic
notifications. Full outage/recovery procedures and private credential locations
remain in `infra-kb/sources/services/dbai24-dns.md`. Preserve student evidence and
pause the timed exercise if a shared service is unavailable; students are not
graded on repairing instructor infrastructure.

## Isolated staging qualification

An instructor may mount the official staging roots in **only** the qualification
blackbox pod and set `http.tls_config.ca_file` to that mounted file. Keep
`insecure_skip_verify: false`; the URL still determines the verified hostname.
The normal course values use public trust and have no staging CA mount. Never
install staging roots in a student's normal browser or system trust store.

One bounded `scale --replicas=0` / restore drill demonstrates probe failure and
`WorkbenchDown` pending/firing/recovery. Restore in a finally/trap handler even
if a check fails. Leave Certificate, Issuer, account and TLS Secrets untouched.
Use existing local expiry/DNS recovery evidence for failure cases rather than
issuing another certificate. Keep Grafana private through SSH/port-forwarding;
optional public exposure needs its own approved hostname/certificate plan and
must not consume the workbench's issuance reservation.
