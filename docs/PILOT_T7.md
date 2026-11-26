# External check T7: what to run, and what to send back

This note is for someone who took **no part** in developing KERN. It has one goal:
numbers produced on **someone else's machine**, compared with ours. If they match,
reproducibility is confirmed by a stranger. If they do not, the divergence is itself a
defect and we investigate it.

**What you do NOT need:** cloning the repository, installing Python/Zig/packages,
reading the code. **What you need:** internet, ~120 MB of free space, and 10 minutes.

## Step 1. Download the release and the script

```bash
mkdir -p ~/kern-t7 && cd ~/kern-t7
base=https://github.com/newmathphys/kern/releases/download/v2.8.26
curl -fSLO "$base/kerna-dist-v2.8.26.tar.gz"
curl -fSLO "$base/SHA256SUMS"
# the script comes from the main branch, NOT from the tag: the tag v2.8.26 carries an
# earlier copy that looked for the key under a different name and did not verify it.
curl -fSLO https://raw.githubusercontent.com/newmathphys/kern/main/tools/pilot_receipt.sh
```

## Step 2. Run the receipt

```bash
KERN_VER=v2.8.26 bash pilot_receipt.sh kerna-dist-v2.8.26.tar.gz 2>&1 | tee receipt.log
```

Invoking through `bash` is deliberate: a file pulled with `curl` has no execute bit, and
`./pilot_receipt.sh` would answer `Permission denied`. The archive is passed as an
argument, so the same 25 MB are not downloaded twice; the script fetches the key
`kern-owner.pub` from the release by itself.

The script will: compare the archive's SHA-256 with the published one, verify the
attestation's Ed25519 signature, unpack the archive, run `kerna --doctor`, check that the
binary carries no AVX-512 (`zmm`) instructions, run a control pair (a deliberately broken
file must give `rc=1`, a clean one `rc=0`), validate SARIF 2.1.0, and confirm that a
missing path yields `rc=2` rather than a success.

## Step 3. Send back

Send `receipt.log` in full. Two lines matter:

```
PILOT RECEIPT: PASS (9/9) — пришлите этот вывод целиком
```

or

```
PILOT RECEIPT: FAIL (k/9) — пришлите вывод: расхождение и есть дефект
```

If it says `FAIL`, do not fix anything and do not re-run: that output is exactly what is
needed.

## What the receipt proves

| Check | What it establishes |
|---|---|
| `sha256 == published` | the archive bytes were not substituted in transit |
| Ed25519 signature | the attestation was issued by the owner of `kern-owner.pub` from the same release |
| `kerna --doctor` | the appliance is self-contained: it carries its own Python and solver |
| `zmm = 0` | the binary runs on a CPU without AVX-512 |
| control pair `rc=1 / rc=0` | the gate distinguishes "a bug was introduced" from "the code is clean" |
| SARIF + `startLine` | the result is usable by GitHub Code Scanning |
| `rc=2` on a missing path | a refusal does not look like success |

## What the receipt does NOT prove

- it does **not** prove that KERN finds all bugs (its coverage is measured; see
  `formal/certification/KNOWN_LIMITATIONS.md`);
- it does **not** check accuracy on your code — that needs a separate run;
- it is **not** a security audit: it confirms the integrity of the artifact and the
  self-sufficiency of the run, not the absence of vulnerabilities in KERN itself.

## Reply template

```
Date:
OS / CPU:            (uname -a)
python3 / tar / openssl / xxd:   (versions)
Verdict line:        PILOT RECEIPT: ...
Divergences:         (if any — which lines)
```

Send: `receipt.log` plus this template. That is enough for T7 to be considered closed, and
for any divergence to be filed as a defect.

## Verified on this very instruction (2026-11-24)

The commands above were executed literally, in an empty directory, with no repository:

```
-rw-r--r-- 25502314  kerna-dist-v2.8.26.tar.gz
-rw-r--r--      182  SHA256SUMS
-rw-r--r--     8048  pilot_receipt.sh          <- from main, not from the tag

-- 1b. Attestation signature (Ed25519) --
  [OK]   attestation signature (Ed25519) 0
PILOT RECEIPT: PASS (9/9)
```

Two mismatches were found by that check and are already fixed in the instruction:

- **the script inside the tag `v2.8.26` is an older copy.** It looked for the key under
  the name `kern_owner_public.pem`, while the release ships `kern-owner.pub`, so the
  signature was honestly reported as a skip (`PASS 8/8`). The script is therefore taken
  from `main`;
- **a downloaded file has no execute bit** → `./pilot_receipt.sh` answers
  `Permission denied`. Hence `bash`, and the archive is passed as an argument (otherwise
  the script downloads the same 27 MB into a temporary directory).
