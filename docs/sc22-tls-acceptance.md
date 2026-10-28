# SC22 packaged TLS acceptance — 26 October 2026

The isolated Windows VM completed the service/private-CA/native SQL TLS group.
No application source change was needed. The full GUI artifact was unsigned
review build `107dcb03-fbf8-42e7-8aef-920e5175c8ad`, SHA-256
`b46774983149682a1b71e4030ac17b681090a540a4f702fc23bb40cbcbdf15cb`.
Its source previously passed all 269 desktop tests. This checkpoint adds live
TLS evidence, rather than repeating the unchanged suite.

## Lab arrangement and scope

The existing `SecondChecking-Test` VM stayed visible and disconnected from
external networking. Guest-only controls left the host mouse/keyboard alone.
Temporary endpoint certificates were issued by an ephemeral private CA, with
`DNS:localhost` identities. Nothing was added to Windows certificate stores.
Keys and private fixture credentials stayed in the guest.

A loopback TLS terminator on ports 5443/5444 forwarded the real matching Flask
routes on port 5002. It was not a mock authentication/report service. The second
port presented an expired certificate. The terminator's backend hop stayed on
guest loopback HTTP. The service's own database account/connection policy was
unchanged; native SQL TLS here tests the desktop's direct read-only connection.

The existing lab MariaDB 11.4.12 instance was gracefully restarted with temporary
certificate paths supplied as process arguments, leaving `database.ini` intact.
Certificates were reloaded with `FLUSH SSL` for the expired/valid SQL cases.
Both the configuration/schema probe and normal desktop connection path used
`VERIFY_IDENTITY`, with plaintext exceptions absent from the test processes.

The frozen native probe used the same Python 3.12 environment and product
configuration/transport/database source as the full artifact. SHA-256 comparison
of the embedded `_mysql` extension, `libssl-3.dll` and `libcrypto-3.dll` proved exact
binary matches. The native client identifies as MariaDB Connector/C 3.3.8 through
mysqlclient 2.2.4. No mocked SQL connection was used.

## Verified results

| Check | Observed result |
| --- | --- |
| SQL trusted CA and correct hostname | TLS 1.2, `ECDHE-RSA-AES256-GCM-SHA384`; real SELECT/schema reads succeeded |
| Configuration/schema and runtime connection entry points | Both connected with identity verification |
| SQL wrong hostname | Native TLS error 2026; configuration probe failed and runtime returned no connection |
| SQL unrelated CA | Native TLS error 2026 |
| SQL expired certificate | Native TLS error 2026; valid certificate restored and positive cases passed again |
| Service trusted private CA | Actual users route and tester login succeeded over TLS 1.3 |
| Service wrong hostname, unrelated CA, expired certificate | Safe `TransportError`, with no authenticated route success |
| Credentialled POST redirect | Redirect refused; destination received zero requests |
| Plain HTTP without the explicit loopback exception | Refused before sending |
| Full packaged GUI | Tester sign-in, `test` lookup, assigned serial list and authenticated saved report 6 readback succeeded |

The GUI's actual process environments were inspected using an allowlist of public
transport fields. They showed HTTPS, the explicit private CA and verified SQL
hostname, with neither plaintext override present. Screenshots show the loaded
order and report 6 with its historical receipt and current reservation.

The first setup attempt exposed an incomplete certificate fixture (missing
authority-key identifiers under Python 3.13's stricter validation) and a stale
pooled backend connection after the deliberate database restart. The fixture was
corrected, readiness recovered and the complete matrix reran successfully.
These setup diagnostics remain in the external ledger; no verification was
disabled and no weaker connection fallback was added.

## Evidence and restoration

External evidence and reproducible harness sources are under
`C:\Users\PCR\Documents\SecondChecking Review\sc22-tls-2026-10-26`.
`verification.json` checks 15 native/service outcomes, exact native binary hashes,
matching product/server source, successful actual-route TLS requests and zero
redirect-target requests. The gateway ledger contains paths/status/TLS metadata,
without headers, authentication bodies or session tokens.

Before/after digests show all six saved reports, six assignment-history rows,
seven receipts, the current `test` reservation and secondary fixture unchanged.
Sign-in/logout naturally exercised authentication/session records; this is not
a claim that every database table was unchanged.

The temporary gateways were stopped. The database restarted with its original
arguments and automatic TLS defaults; both original configuration files retained
their SHA-256 digests. The full GUI returned to the usual loopback lab settings.
No VM clone, snapshot or OVA export was created or rewritten.

## Remaining acceptance

**Three broad groups remain:** reviewed source/hosted CI with signed upgrade,
failed-update and rollback; elevated maintenance on a suitable disposable machine;
and physical hardware, mixed-monitor DPI and longer bench acceptance.

This closes representative isolated packaged TLS acceptance. Rollout still needs
the deployment's actual final HTTPS address, CA chain/hostname, SQL certificate
and read-only account configured and smoke-tested. The temporary lab CA is not
a deployment trust anchor, and this unsigned review build is not a release.
