# CertChain Caliper Benchmarks (Phase 4)

Hyperledger Caliper workspace for benchmarking the `certchain` chaincode
(`issueMicroCredential` write path, `verifyCredential` read path) across the
50-500 transaction range used in the roadmap's Phase 4 evaluation.

## Status

This workspace is fully installed and config-validated in this environment,
but **no benchmark has actually been executed here** — there is no live
Fabric network (peers/orderer/CA) running in this sandbox to run it against.
Validation performed so far:

- `npm install` — installs `@hyperledger/caliper-cli`, `@hyperledger/caliper-fabric`.
- `npx caliper bind --caliper-bind-sut fabric:2.2` — binds the connector to
  `fabric-network@2.2.20`, matching the SDK version this repo already uses
  elsewhere (`api/package.json`, `wallet/wallet_setup.js`).
- `npx caliper launch manager ... --caliper-flow-only-test` — confirms the
  network config parses, the Fabric connector loads, and it correctly
  detects the installed SDK version (`2.2.20`). It then fails, as expected,
  at identity-manager initialization because `wallet/store/` doesn't exist
  yet in this sandbox — that directory is only populated by enrolling
  against a real Fabric CA (see below). This is the correct failure point:
  it proves the network/benchmark config themselves are wired correctly,
  and that the only missing piece is a live network.
- Both workload modules (`workloads/issueCredential.js`,
  `workloads/verifyCredential.js`) load and construct cleanly under Node.

No throughput/latency numbers exist yet. Do not treat any number in this
directory as a measured result unless it was produced by an actual
`npm run benchmark` run against a live network, with the resulting
`reports/report.html` committed alongside it.

## Running for real

1. Bring up the Fabric test network and deploy the `certchain` chaincode,
   and enroll the identities `wallet/wallet_setup.js` expects
   (`admin`, `famu-institution`, `public-verifier`, `FAMU10001`) — this is
   exactly what `start.sh` at the repo root already does.
2. From this directory:
   ```
   npm install
   npx caliper bind --caliper-bind-sut fabric:2.2   # already done once; re-run only if node_modules is wiped
   npm run validate     # dry-run: parses config, connects identities, doesn't send transactions
   npm run benchmark     # runs all rounds in benchconfig.yaml, writes reports/report.html
   ```

## Layout

- `networks/certchain-network.yaml` — Caliper network config. Points at the
  same `config/connection.json` and `wallet/store` file-system wallet the
  rest of CertChain already uses, so no separate identity setup is needed.
- `benchconfig.yaml` — round definitions: `issueCredential` and
  `verifyCredential`, each run at txNumber 50/100/200/300/400/500, 2
  concurrent workers (matching the roadmap's "2 HEI nodes" framing),
  `fixed-load` rate control. Also enables the `process-usage` resource
  monitor against `node api/server.js`.
- `workloads/issueCredential.js` — drives `issueMicroCredential` as the
  `famu-institution` identity with a payload that clears the real
  eligibility rules in `chaincode/certchain.js` (GPA 3.5, 3 FCCS courses,
  bert_confidence 0.9), so measured transactions exercise the actual
  ELIGIBLE/ISSUED code path, not the early-reject path.
- `workloads/verifyCredential.js` — seeds a small pool of real credentials
  during `initializeWorkloadModule` (before the timed round starts), then
  cycles through their `credHash`es as the `public-verifier` identity for
  the timed `verifyCredential` reads.
- `reports/` — output directory for generated HTML reports (git-ignored;
  only `.gitkeep` is tracked).
