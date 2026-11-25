# syntax=docker/dockerfile:1

# ---- stage 1: prove the code parses and compiles, install nothing -------------
FROM python:3.12-slim AS build
WORKDIR /src
COPY domingo.py ./
COPY static ./static
COPY tests ./tests
COPY tools ./tools
RUN python -c "import ast,pathlib; ast.parse(pathlib.Path('domingo.py').read_text('utf-8'))" \
 && python -m compileall -q domingo.py tests/fake_engine.py tools/boot-check.py

# ---- stage 2: runtime ---------------------------------------------------------
# The app is one file and the standard library: no pip install, no build toolchain,
# nothing from stage 1 except the source that was checked there.
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Domingo" \
      org.opencontainers.image.description="A small chat client for a model server on your own machine" \
      org.opencontainers.image.source="https://github.com/iulianduminica/Domingo" \
      org.opencontainers.image.licenses="Other"

RUN groupadd -g 10001 domingo \
 && useradd -u 10001 -g domingo -m -s /usr/sbin/nologin domingo

WORKDIR /app
COPY --from=build --chown=domingo:domingo /src/domingo.py /app/domingo.py
COPY --from=build --chown=domingo:domingo /src/static     /app/static
COPY --from=build --chown=domingo:domingo /src/tools      /app/tools
COPY --chown=domingo:domingo docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod 755 /app/docker-entrypoint.sh \
 && mkdir -p /data && chown domingo:domingo /data

ENV DOMINGO_HOST=127.0.0.1 \
    DOMINGO_PORT=8899 \
    DOMINGO_TOKEN="" \
    DOMINGO_URL="" \
    DOMINGO_KEY="" \
    DOMINGO_MODEL="" \
    DOMINGO_NAME="" \
    DOMINGO_ADVERTISE=""

VOLUME ["/data"]
EXPOSE 8899
USER domingo

# /healthz answers with no credentials, which is what makes this possible.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,sys,urllib.request; u='http://127.0.0.1:%s/healthz' % os.environ.get('DOMINGO_PORT','8899'); sys.exit(0 if urllib.request.urlopen(u,timeout=4).status==200 else 1)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
