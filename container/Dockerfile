FROM python:3.12-alpine@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/hillemacher/bitbucket-pr-comments-exporter" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY bb_pr_export ./bb_pr_export
RUN python -m pip install --no-cache-dir --upgrade pip==26.3 \
    && python -m pip install --no-cache-dir '.[mcp]' \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip
COPY container/entrypoint.py /app/entrypoint.py
USER 65532:65532
WORKDIR /tmp
EXPOSE 9000
ENTRYPOINT ["python3", "/app/entrypoint.py"]
CMD ["serve"]
