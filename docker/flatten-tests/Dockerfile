FROM python:3.13-slim

RUN pip install uv

WORKDIR /app

COPY docker/flatten-tests/pyproject.toml docker/flatten-tests/uv.lock ./
RUN uv sync --frozen

COPY docker/flatten-tests/flatten_tests ./flatten_tests
COPY docker/flatten-tests/tests ./tests
COPY .devin/flatten-tests.json /repo/.devin/flatten-tests.json

ENV REPO_ROOT=/repo

CMD ["uv", "run", "python", "-m", "flatten_tests.main"]
