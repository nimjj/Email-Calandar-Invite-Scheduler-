# ─────────────────────────────────────────────────────────────
#  Dockerfile — AWS Lambda Container Image (Python 3.11)
# ─────────────────────────────────────────────────────────────
#  Builds a production container for the Herbert calendar
#  scheduling Lambda function.  No credential files are baked
#  into the image; OAuth tokens are fetched at runtime from
#  AWS Secrets Manager.
# ─────────────────────────────────────────────────────────────

FROM public.ecr.aws/lambda/python:3.11

# ── Install Python dependencies ─────────────────────────────
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir \
        --target "${LAMBDA_TASK_ROOT}" \
        -r "${LAMBDA_TASK_ROOT}/requirements.txt"

# ── Copy application source ─────────────────────────────────
COPY lambda_function.py  ${LAMBDA_TASK_ROOT}/
COPY secrets_manager.py  ${LAMBDA_TASK_ROOT}/

# ── Runtime entrypoint ──────────────────────────────────────
CMD ["lambda_function.lambda_handler"]
