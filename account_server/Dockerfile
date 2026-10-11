FROM python:3.12-slim
WORKDIR /app
COPY account_server /app/account_server
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
ENV TOONSHELF_DB=/data/accounts.sqlite3
EXPOSE 8080
CMD ["python", "-m", "account_server.server"]
