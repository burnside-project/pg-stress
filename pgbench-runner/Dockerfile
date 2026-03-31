FROM postgres:15-alpine

RUN apk add --no-cache bash jq coreutils bc

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/ /opt/pgbench/scripts/
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["entrypoint.sh"]
