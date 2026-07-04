FROM alpine:3.20

RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq

WORKDIR /repo

# リポジトリのソースを組み込む（クレデンシャルは含まない）
COPY . .

COPY docker/flatten-tests/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
