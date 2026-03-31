FROM golang:1.23-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY main.go schema.sql ./
RUN CGO_ENABLED=0 go build -o /soak-load .

FROM alpine:3.21
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /soak-load /usr/local/bin/soak-load
COPY --from=builder /app/schema.sql /usr/local/share/schema.sql
ENTRYPOINT ["soak-load"]
