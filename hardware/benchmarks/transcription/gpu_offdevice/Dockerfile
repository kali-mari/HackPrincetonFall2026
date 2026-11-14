ARG BASE_IMAGE=debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
FROM ${BASE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates cmake g++ make git python3 libvulkan-dev glslc binutils \
    && rm -rf /var/lib/apt/lists/*
COPY build.sh /build.sh
ENTRYPOINT ["sh", "/build.sh"]
