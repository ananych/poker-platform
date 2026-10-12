# ADR 0001 — Modular monolith, single always-on backend

- Status: Accepted (SDD v1.0 §1)
- Date: 2026-10-10

## Context
10–30 concurrent users, 2–9 seats per table, strict consistency and privacy requirements.

## Decision
Next.js client; FastAPI server; managed PostgreSQL; secure WebSocket. One always-on backend
instance with ONE Uvicorn worker. No Redis/Kafka/microservices/Kubernetes in v1.
Server state is authoritative; mutations serialized per room (in-process mutex + `SELECT … FOR
UPDATE` + room version check) and committed before any broadcast.

## Consequences
- Simple ops and reasoning about ordering; horizontal scaling requires distributed coordination
  (out of scope for v1).
- The pure poker engine (`app/domain/poker`) is callable without HTTP/WS/DB and is the unit of
  correctness testing.
