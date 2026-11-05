FROM python:3.12-slim
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
RUN pip install --no-cache-dir '.[mcp]'
COPY container/entrypoint.py /app/entrypoint.py
USER 65532:65532
WORKDIR /tmp
EXPOSE 9000
ENTRYPOINT ["python3", "/app/entrypoint.py"]
CMD ["serve"]
