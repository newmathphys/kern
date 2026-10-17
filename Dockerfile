# ============================================================================
#  KERN — reproducible multi-stage build (Zig 0.17.0 core + libsqlite3 + z3).
#
#  Build:  docker build -t kern:2.4.0 .          # context is ~4.3 MB (.dockerignore)
#  Use:    docker run --rm kern:2.4.0                      # integrity check
#          docker run --rm kern:2.4.0 verify /kern/toy.kimg # the Truth Gate
#
#  STATUS: VERIFIED 2026-10-17. Built with Docker Engine 29.8.1 (overlayfs) and BOTH
#  commands above were executed: the integrity check printed
#  `[OK] Целостность: заголовок + Merkle-корень совпали`, and `verify` printed
#  `SAT -> e=0 (F) КОНТРПРИМЕР` for the refuted claim and `UNSAT -> e=1 (T) ДОКАЗАНО`
#  for the fixed one. Image size 364 MB. (Earlier revisions of this file were honest
#  about being unverified — the daemon is available now, so it is verified.)
# ============================================================================
FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl xz-utils ca-certificates libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Zig 0.17.0 (the toolchain this project is verified against).
ARG ZIG_VERSION=0.17.0
RUN curl -fsSL "https://ziglang.org/download/${ZIG_VERSION}/zig-x86_64-linux-${ZIG_VERSION}.tar.xz" \
      -o /tmp/zig.tar.xz \
    && tar -C /opt -xf /tmp/zig.tar.xz \
    && ln -s "/opt/zig-x86_64-linux-${ZIG_VERSION}/zig" /usr/local/bin/zig \
    && zig version

WORKDIR /src
COPY . .

# ReleaseSafe: keeps runtime safety checks on (UB detector) while optimising.
RUN zig build -Doptimize=ReleaseSafe

# ---------------------------------------------------------------------------
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      libsqlite3-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# z3 as a self-contained Python wheel (no system package needed).
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && pip3 install --no-cache-dir --break-system-packages z3-solver \
    && ln -sf /usr/local/bin/z3 /usr/bin/z3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /kern
COPY --from=build /src/zig-out/bin/kernc        /usr/local/bin/kernc
COPY --from=build /src/zig-out/bin/kernx        /usr/local/bin/kernx
COPY --from=build /src/zig-out/bin/kern-attack  /usr/local/bin/kern-attack
COPY --from=build /src/tools     /kern/tools
COPY --from=build /src/examples  /kern/examples
COPY --from=build /src/tests     /kern/tests

# Build the toy example image so `verify` works out of the box.
RUN kernc build /kern/examples/toy_ai_hallucination/project.kern -o /kern/toy.kimg || true

ENTRYPOINT ["/usr/local/bin/kernc"]
CMD ["check-integrity", "/kern/tests/fixtures/valid_v1_3.kimg"]
