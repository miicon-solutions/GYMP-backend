# Container security review — 16 November 2026

The linked [Docker Hub Python image](https://hub.docker.com/layers/library/python/3.14-slim/images/sha256-ac25e5afbfdb4a94ff99cc24b0345719210133144481480bcba6085efa36a341) reports **8 high** findings for its upstream `linux/amd64` image. That is an upstream-image result, not a scan of this application's final filesystem.

We independently scanned the previous and updated production images with **Trivy 0.76.2**, including OS and application-package vulnerabilities. Database updated: 16 November 2026 00:56 +06. Scans included all critical/high findings, without ignoring unfixed vulnerabilities or applying a VEX/ignore list. Docker Hub and Trivy use different advisory sources/counting, so their totals are not directly comparable.

| Production image | Critical matches | High matches | Unique critical/high advisories | Matches with an available fix |
| --- | ---: | ---: | ---: | ---: |
| Previous image | 0 | 54 | 18 | 7 |
| Updated image | 0 | 47 | 11 | 0 |

A match means one advisory against one installed package. Multiple binary packages can share one source-package CVE; the remaining 47 matches represent 11 unique CVEs.

## Changes made

- Explicitly select `python:3.14.10-slim-trixie`, preserving Python 3.14 compatibility and the Debian release already in use. Comparing `3.14.10-slim-bookworm` found 2 critical findings, so switching to that older release was not an improvement.
- Apply available Debian package updates in a shared base stage. This installs the fixed `zlib1g` release `1:1.3.dfsg+really1.3.1-1+deb13u1`, removing matches for CVE-2026-76844 and CVE-2026-85091. [Debian's fix record](https://security-tracker.debian.org/tracker/CVE-2026-76844).
- Remove unused system `pip` and its `ensurepip` bootstrap wheels from the runtime. Their vendored dependencies produced five high matches: msgpack (CVE-2026-114613 and GHSA-6v7p-g79w-8964), setuptools (CVE-2025-47273), and urllib3 (CVE-2026-97687 and CVE-2026-97689).
- Install dependencies with `uv` in a separate build stage, then copy only the locked virtual environment into runtime. Build tooling/caches are not shipped. The application itself already uses patched msgpack 1.2.4 and urllib3 2.8.0; `uv.lock` is unchanged.
- Keep the existing non-root UID 10001 and restrict writable application paths to media/static directories. Test dependencies are isolated in the `test` target. Deployment still selects `/app/entrypoint.sh` and port 8000.

Relevant Dockerfile locations: base selection at line 8, package updates at line 18, runtime dependency copy at line 35, installer removal at line 40, and non-root user at line 50.

## Remaining vendor findings

All remaining matches are Debian packages for which this scan reports no released fix. They remain visible and require future vendor updates/reassessment; this is not a claim of a vulnerability-free image.

| Source/component | Unique CVEs | Affected installed packages |
| --- | --- | --- |
| util-linux | CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| ACL | CVE-2026-54369 | libacl1 |
| ncurses | CVE-2025-69720 | libncursesw6, libtinfo6, ncurses-base, ncurses-bin |
| SQLite | CVE-2026-119373, CVE-2026-119374, CVE-2026-119379 | libsqlite3-0 |
| systemd | CVE-2026-16742 | libsystemd0, libudev1 |
| Perl | CVE-2026-9538 | perl-base (fix deferred) |

Vendor prioritization differs from scanner severity. For example, [Debian's CVE-2026-78408 record](https://security-tracker.debian.org/tracker/CVE-2026-78408) describes a privileged `nsenter --join-cgroup` operation and classifies the Trixie issue as minor/no-DSA. The image's administrative-command packages still appear in the complete scan; no blanket exploitability exemption was applied.

## Verification and repeat checks

- Production and test images build successfully.
- Full suite inside the rebuilt test image: 162 tests passed against disposable PostgreSQL databases.
- Production smoke: `.env` loading, migrations, runtime static collection, non-root Gunicorn, database readiness and static asset delivery on port 8000.
- Runtime checks confirm system pip, ensurepip and uv are absent; application packages and the secret loader remain usable.
- Final production scan: 0 critical, 47 high matches, 0 matches with an available fix.

Rebuild periodically to pick up upstream fixes and review the pinned Python patch version. Package-update layers can be cached; use a fresh build when investigating advisories:

```bash
docker build --pull --no-cache --target production -t gymp-backend:review .
trivy image --scanners vuln --severity HIGH,CRITICAL gymp-backend:review
```

Alternatively, `docker save` the image and scan the archive with `trivy image --input /path/to/image.tar`, as in this review. [Trivy image-scanning documentation](https://trivy.dev/docs/latest/target/container_image/).

The IDE may continue to flag the upstream `FROM` image until its maintainers publish a patched base. Review the final image scan alongside that warning. Counts are a dated snapshot and may change as advisory databases and vendor classifications change.
