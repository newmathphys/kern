# =========================================================================
#  KERN — многостадийная сборка (Zig-ядро + libsqlite3 + z3).
#  ВНИМАНИЕ: это рабочая оболочка; проверить сборку внутри Docker в текущем
#  окружении не удалось (нет docker). Статус — «написано, не измерено».
# =========================================================================
FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl xz-utils ca-certificates libsqlite3-dev z3 \
    && rm -rf /var/lib/apt/lists/*
ARG ZIG_VERSION=0.13.0
RUN curl -fsSL https://ziglang.org/download/${ZIG_VERSION}/zig-linux-x86_64-${ZIG_VERSION}.tar.xz \
      -o /tmp/zig.tar.xz \
    && tar -C /opt -xf /tmp/zig.tar.xz \
    && ln -s /opt/zig-linux-x86_64-${ZIG_VERSION}/zig /usr/local/bin/zig
WORKDIR /src
COPY . .
RUN zig build -Doptimize=ReleaseSafe

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libsqlite3-0 z3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /kern
COPY --from=build /src/zig-out/bin/kernc /usr/local/bin/kernc
COPY --from=build /src/zig-out/bin/kernx /usr/local/bin/kernx
COPY --from=build /src/zig-out/bin/kern-attack /usr/local/bin/kern-attack
COPY --from=build /src/tools /kern/tools
COPY --from=build /src/examples /kern/examples
COPY --from=build /src/tests /kern/tests
ENTRYPOINT ["/usr/local/bin/kernc"]
CMD ["check-integrity", "/kern/tests/fixtures/valid_v1_3.kimg"]
