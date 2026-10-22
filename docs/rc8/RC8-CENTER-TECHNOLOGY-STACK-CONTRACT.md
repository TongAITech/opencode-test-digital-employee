# RC8 Center Technology Stack Contract

Status: FROZEN
Purpose: freeze the formal RC8 Center product technology stack and prevent the W1 minimal protocol server or temporary persistence adapters from becoming the production architecture by inertia.

## 1. Binding technology stack

The formal RC8 Center product stack is:

- Backend API framework: FastAPI
- API/data validation: Pydantic
- Persistence: PostgreSQL
- ORM/persistence mapping: SQLAlchemy
- Schema migration: Alembic
- Coordination/lease/queue/cache: Redis
- Frontend: Vue 3
- Frontend language: TypeScript
- Frontend build tool: Vite
- Frontend routing: Vue Router
- Frontend state management: Pinia
- Web serving/reverse proxy: Nginx
- Center deployment: Docker Compose first-class deployment
- Artifact storage: repository abstraction with filesystem/object-storage capable implementation; artifact metadata remains durable in Center persistence

Exact library/runtime versions are capability-qualified and must follow `CAPABILITY_BASED_NO_EXACT_VERSION_PIN`; this contract freezes technology families and architectural roles, not brittle point versions.

## 2. Formal Center topology

```text
Client Browser
    |
    v
Nginx
    |-----------------------> Vue 3 + TypeScript static product UI
    |
    +-----------------------> FastAPI Product/Node/Artifact APIs
                                  |
                                  v
                       Application/Domain Services
                                  |
             +--------------------+--------------------+
             |                    |                    |
             v                    v                    v
        PostgreSQL              Redis             Artifact Store
             |                    |
             |                    +-- WorkItem Lease
             |                    +-- Resource Lease
             |                    +-- Queue/coordination
             |                    +-- transient cache
             |
             +-- Production/Version/Requirement/SST
             +-- TestRun/Mission/Stage/Attempt
             +-- Gap/Invalidation/Sufficiency/Release
             +-- Case/ExecutableSpec/Coverage/Defect
             +-- Node/Capability/Artifact metadata
             +-- Knowledge/Skill/System Behavior Graph
```

Office-PC / Xinchuang nodes remain outbound clients of Center:

```text
RC8 Node Agent -> Center APIs
      |
      +-> DSH
      +-> RC7/RC8 execution adapters
```

AI model interaction remains on eligible execution nodes. Center does not require direct bank-LLM connectivity to own durable mission truth.

## 3. Backend architecture requirements

FastAPI is an adapter, not the domain core.

Mandatory logical structure:

```text
rc8_center/
  domain/
  application/
  infrastructure/
    postgres/
    redis/
    artifact/
  api/
    fastapi/
  runtime/
    r1/
```

Domain/Mission/Gap/Sufficiency/R1 logic MUST remain framework-independent enough to be exercised without HTTP.

Forbidden:
- business rules implemented only inside FastAPI route functions;
- UI-derived status becoming durable truth;
- Node writing PostgreSQL directly;
- Redis becoming authoritative mission truth;
- replacing R1 Event Stream with web/API logs;
- using the stdlib W1 HTTP server as the formal production product server.

## 4. Status of the current stdlib HTTP server

`rc8_center/http_server.py` is retained only as:
- minimal protocol/reference adapter;
- low-dependency contract test server;
- W1 Reality/fallback test boundary where explicitly required.

It MUST NOT be expanded into the formal product backend once FastAPI construction begins.

Any production/product capability added after this contract that is only exposed through the stdlib server remains `PARTIAL` until exposed through the formal FastAPI application.

## 5. PostgreSQL authority

PostgreSQL is the formal durable Center persistence layer.

Durable domains include at minimum:
- ProductionBatch/SystemVersion/Requirement/RequirementDeliveryScope/Application/SST;
- TestRun/MissionGraph/Stage/WorkItem/Attempt;
- TestCase/ExecutableSpec/Oracle metadata;
- CoverageObservation/Gap/Invalidation/SufficiencyEvaluation/ReleaseDecision;
- Artifact/Evidence metadata;
- Defect/RCA/regression linkage;
- Node/Capability;
- Knowledge/Skill/System Behavior Graph;
- Report snapshots and product projections where materialized.

JSON-file repositories are temporary W-A/W1 fallback adapters only. They may remain for contract tests but cannot satisfy `ARCH-013` or production Center deployment closure.

Schema changes MUST use Alembic migrations. Manual production-schema mutation is not an accepted deployment path.

## 6. Redis role

Redis owns only transient/distributed coordination concerns, including:
- WorkItem leases;
- Resource leases;
- dispatch/task queues;
- distributed locks where needed;
- short-lived node/runtime coordination;
- caches;
- optional pub/sub or streams for non-authoritative delivery.

Redis data loss/restart MUST NOT erase Mission/TestRun/Attempt/Gap/Sufficiency truth.

Recovery requirement:
`Redis restart -> reconcile from PostgreSQL + R1 -> resume safely without duplicate ownership or fabricated completion`.

## 7. R1 and projection rule

R1 Event Stream remains runtime truth.

Required runtime chain:

```text
Node Runtime Event
-> R1 persistence
-> Center projector/application service
-> PostgreSQL durable projection/domain state
-> Product API
-> Vue UI
```

Redis can help deliver/coordinate but cannot bypass this truth chain.

Crash window tests MUST cover:
- R1 accepted before PostgreSQL projection commit;
- replay/idempotent projection after Center restart;
- duplicate runtime event;
- stale/late event;
- Redis restart during active leases.

## 8. Frontend architecture requirements

Formal frontend stack:
- Vue 3 Composition API
- TypeScript
- Vite
- Vue Router
- Pinia

Recommended module organization follows the 13 frozen product surfaces:

```text
center-web/src/
  app/
  router/
  stores/
  modules/
    production/
    version/
    requirement/
    code-analysis/
    business-flow/
    api/
    test-case/
    test-run/
    report/
    defect/
    knowledge/
    node/
    system/
  components/
    trace/
    evidence/
    coverage/
    gap/
    attempt/
    status/
```

Shared product components should include equivalents of:
- Attempt timeline;
- Evidence viewer;
- Coverage matrix/detail;
- Gap route/repair history;
- Traceability navigation;
- Sufficiency explanation.

The UI MUST consume Center projections. It MUST NOT infer PASS/SUFFICIENT/RELEASE from raw counts such as `failures == 0`.

## 9. UI framework/style constraint

A component library may be used for low-level primitives if it does not control the product information architecture or visual language.

The frozen product rules remain:
- Chinese-first;
- restrained Apple-inspired visual hierarchy;
- left navigation + right content;
- no dashboard-first layout;
- no giant decorative cards;
- no oversized colored sidebar/domain navigation;
- status color only where semantically useful;
- large readable detail surfaces rather than nested small dialogs.

If Element Plus or another library is adopted, RC8-owned wrapper/design tokens MUST control tables/forms/dialogs/status/trace/evidence presentation.

## 10. Nginx and product serving

Nginx is the formal product web edge for Center deployment:
- serves built Vue static assets;
- reverse-proxies `/api/` to FastAPI;
- supports same-origin deployment to simplify bank networking;
- provides controlled request/body limits for Artifact/API paths where applicable.

Direct Uvicorn exposure may be used for development/integration tests but is not the intended final product edge.

## 11. Docker Compose first-class deployment

The formal Center deployment topology is at minimum:

```text
rc8-web        Nginx + Vue dist
rc8-center     FastAPI/Uvicorn application
rc8-worker     Center background/projector jobs where separated
postgresql
redis
artifact-storage
```

A modular-monolith Center remains valid; `rc8-worker` may initially run the same codebase with a different process role. This contract does not require premature microservices.

The deployment package MUST support:
- clean install;
- schema migration;
- health/readiness checks;
- restart;
- PostgreSQL/Redis outage/recovery tests;
- upgrade preserving durable data;
- rollback/migration safety strategy;
- no hidden public-internet runtime dependency in bank deployment.

## 12. Development/runtime version separation

Node and Center runtime requirements are independent:
- Node continues to support the bank office-PC baseline including Python 3.8-compatible RC8 Node code where required;
- Center Docker images carry their own supported Python/Node build runtimes.

Do not constrain the formal Center framework to the office-PC Python runtime merely because Node must remain compatible.

## 13. Required CI/reality gates

Technology-stack closure requires separate proof:

1. `CENTER_STACK_CONTRACT` machine validation.
2. Real PostgreSQL + Redis integration deployment.
3. PostgreSQL schema/migration test.
4. Repository integration test against PostgreSQL.
5. Redis lease/queue/TTL/restart test.
6. FastAPI API contract/integration test.
7. Vue build/type-check/component/product tests.
8. Nginx same-origin API/static smoke.
9. Full Docker Compose Center smoke.
10. Center restart + PostgreSQL/Redis restart/replay recovery.
11. Product UI consumes real Center projections.
12. Target-bank/server deployment reality before production architecture is called `REALITY_VERIFIED`.

A service container starting successfully is infrastructure proof only; it does not close the Center adapter/product capability.

## 14. Required status boundaries

Until implemented and proven, report truthfully:

```text
ARCH:CENTER_TECH_STACK = FROZEN
INFRA:POSTGRES_REDIS_TEST_ENV = IMPLEMENTED/CI_VERIFIED only after its real integration gate passes
CENTER:POSTGRES_ADAPTER = OPEN until implemented
CENTER:REDIS_COORDINATION = OPEN until implemented
CENTER:FASTAPI_PRODUCT_API = OPEN until implemented
PRODUCT:VUE_WEB = OPEN until implemented
DEPLOY:CENTER_DOCKER_COMPOSE = OPEN until implemented
```

The technology decision being frozen does not itself imply implementation completion.

## 15. Change control

Changing any of the following requires an explicit architecture decision that updates Architecture Baseline, Product Baseline, this contract, Closure Matrix, Wave Gates and machine governance together:
- FastAPI as formal backend API framework;
- PostgreSQL as durable Center persistence;
- Redis as transient coordination/lease/queue/cache;
- Vue 3 + TypeScript + Vite as formal product frontend;
- Nginx as final web edge;
- Docker Compose as first-class Center deployment.

Silent substitution during implementation is forbidden.
