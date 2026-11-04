FROM python:3.12-slim
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
