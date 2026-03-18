# Hermes Stream Roadmap

> Last updated: 2026-03-16
> Status: Phase 3 진행 중 (89%) — Collect/Process/Export 리네이밍 완료

---

## Vision

**"The .NET NiFi"** — Enterprise-grade, lightweight data processing platform.

NiFi의 강점(per-item tracking, provenance)을 가져가되,
.NET 기반으로 가볍고, non-developer가 Web UI에서 운영 가능한 플랫폼.

### Pipeline Category Model

| Stage | Purpose | Color | Examples |
|---|---|---|---|
| **Collect** | 데이터 수집 (Source/Ingest) | Blue | FTP/SFTP, Kafka Consumer, REST API, DB CDC, File Watcher, MQTT |
| **Process** | 변환/분석/필터링/라우팅 | Purple | Anomaly Detector, Data Transformer, Dedup Filter, Content Router |
| **Export** | 목적지 전달 (Sink/Deliver) | Emerald | Kafka Producer, S3 Upload, DB Writer, Webhook, TIBCO RV Publisher |

---

## Hermes의 핵심 강점 (Differentiators)

### 1. Job-Level Tracking
> 모든 데이터 아이템의 수집→분석→전송 전 과정을 개별 추적.
> NiFi 외에는 아무도 하지 않는 기능.

### 2. Recipe Management for Non-Developers
> SW 개발자가 아닌 운영자가 Web UI에서 수집 설정, 알고리즘 파라미터를 변경.
> JSON Schema → 자동 폼 생성. 버전 관리 + diff/compare.
> 전역 Recipe Management 페이지에서 모든 Recipe를 중앙 관리.

### 3. First-Class Reprocessing
> 실패 건 단건/일괄 재처리. 특정 Step부터 재시작. 최신 Recipe 적용 선택.
> 경쟁 제품 중 이걸 제대로 하는 곳이 없음.

### 4. NiFi-Friendly, Not NiFi-Dependent
> 기존 NiFi 레거시를 그대로 활용하면서 Hermes의 UI/추적/재처리 레이어를 씌울 수 있음.
> NiFi 없이도 독립 실행 가능.

### 5. Plugin Protocol (gRPC, Language-Agnostic)
> 알고리즘은 Docker container로 격리. gRPC/Kafka로 통신.
> Python, R, C++, Java 등 어떤 언어로든 플러그인 작성 가능.

### 6. Disk-Based Content Repository
> NiFi처럼 대용량 데이터를 디스크 기반으로 처리.
> 메모리 부족 없이 GB 단위 데이터 파이프라인 운영.

---

## Phase 0: Design ✅ COMPLETE

| Item | Status | 산출물 |
|---|---|---|
| 전체 아키텍처 설계 | ✅ | `docs/ARCHITECTURE.md` |
| 데이터 수집 설계 | ✅ | `docs/DATA_COLLECTION_DESIGN.md` |
| NiFi 연동 설계 | ✅ | `docs/NIFI_INTEGRATION.md` |
| 테스트 전략 | ✅ | `docs/TEST_STRATEGY.md` |
| DB 스키마 | ✅ | `backend/database/schema.sql` |
| Python 프로토타입 | ✅ | `backend/`, `webapp/`, `plugins/` |
| 벤치마크 Gap 분석 | ✅ | 17개 Gap 식별 (P0~P3) |
| .NET Solution 설계 | ✅ | `docs/DOTNET_SOLUTION_DESIGN.md` |
| gRPC Protocol 설계 | ✅ | `protos/` |
| Domain Interface 설계 | ✅ | `docs/DOMAIN_INTERFACES.md` |

---

## Phase 1: MVP ✅ COMPLETE

- [x] ASP.NET Core 8 Web API + EF Core + PostgreSQL
- [x] Definition/Instance/Pipeline CRUD + Recipe 버전 관리
- [x] Monitoring Engine (File Watcher, API Poller, Kafka Consumer)
- [x] Processing Engine (Orchestrator, Snapshot, Event Log, Reprocess)
- [x] Plugin System (gRPC Protocol v2, SDK, 8 built-in plugins)
- [x] Web UI (Pipeline Designer, Recipe Editor, Monitor, Job Explorer)
- [x] Docker Compose, Health Check, Serilog

---

## Phase 2: Production-Ready ✅ COMPLETE

- [x] Back-pressure, Dead Letter Queue, Schema Discovery
- [x] Content Repository (디스크 기반 대용량)
- [x] Exactly-Once + Graceful Shutdown
- [x] Observability (Prometheus + Grafana)
- [x] Retry 정교화 (exponential backoff + jitter + Polly)
- [x] NiFi Integration (Bridge, Provenance, Parameter Context)
- [x] 161 tests, 90%+ coverage

---

## Phase 3: Enterprise — IN PROGRESS (89%)

### 3A. Collect/Process/Export Module 강화 🔥 PRIORITY

#### Collect Connectors (목표: 15+ native connectors)

| Connector | Category | Priority | Status | Description |
|---|---|---|---|---|
| **FTP/SFTP Collector** | File | P0 | 🔄 | 재귀 탐색, 최신순/오래된순 정렬, regex 필터, 완료 감지 |
| **Kafka Consumer** | Streaming | P0 | ✅ | Topic 구독, consumer group, offset 관리 |
| **REST API Collector** | API | P0 | ✅ | GET/POST, auth, pagination, polling |
| **File Watcher** | File | P0 | ✅ | Directory 감시, glob 패턴 |
| **Database CDC** | Database | P0 | ✅ | Timestamp/sequence 기반 변경 추적 |
| MQTT Subscriber | IoT | P1 | ⬜ | Topic 구독, QoS, retain 메시지 |
| OPC-UA Client | Industrial | P1 | ⬜ | 설비 데이터 수집, subscription/polling |
| TCP/UDP Socket | Network | P1 | ⬜ | Raw socket 데이터 수신 |
| AMQP Consumer | Messaging | P1 | ⬜ | RabbitMQ, ActiveMQ 호환 |
| JMS Consumer | Messaging | P2 | ⬜ | Java Message Service 호환 |
| TIBCO RV Listener | Messaging | P2 | ⬜ | TIBCO Rendezvous 메시지 수신 |

#### Process Connectors (목표: 10+ native processors)

| Processor | Category | Priority | Status | Description |
|---|---|---|---|---|
| **Anomaly Detector** | Analytics | P0 | ✅ | Z-score, IQR, modified z-score |
| **Data Transformer** | Transform | P0 | ✅ | JSON/CSV 변환, field mapping |
| **Dedup Filter** | Filter | P0 | ✅ | Key 기반 중복 제거 |
| **Content Router** | Routing | P0 | ✅ | 조건부 분기 |
| JSON Transform | Transform | P0 | ✅ | JMESPath 기반 변환 |
| CSV-JSON Converter | Transform | P0 | ✅ | 양방향 변환 |
| Merge Content | Batch | P0 | ✅ | 다건 병합 (NiFi MergeContent) |
| Split Records | Batch | P0 | ✅ | 배치 분할 (NiFi SplitRecord) |
| Schema Validator | Validation | P1 | ⬜ | JSON Schema / Avro 검증 |
| Record Enricher | Enrichment | P1 | ⬜ | 외부 API/DB lookup 보강 |

#### Export Connectors (목표: 12+ native connectors)

| Connector | Category | Priority | Status | Description |
|---|---|---|---|---|
| **Kafka Producer** | Streaming | P0 | ⬜ | Topic 발행, partitioning, acks |
| **S3 Upload** | Storage | P0 | ⬜ | Bucket, prefix, format, compression |
| **DB Writer** | Database | P0 | ⬜ | PostgreSQL/MSSQL upsert |
| **File Output** | File | P0 | ✅ | JSON/CSV/text 파일 출력 |
| **Webhook Sender** | API | P0 | ⬜ | HTTP POST, retry, auth |
| FTP/SFTP Upload | File | P1 | ⬜ | 원격 서버 파일 전송 |
| TIBCO RV Publisher | Messaging | P1 | ⬜ | TIBCO Rendezvous 메시지 발행 |
| AMQP Producer | Messaging | P1 | ⬜ | RabbitMQ, ActiveMQ 발행 |
| Elasticsearch Writer | Search | P1 | ⬜ | Index, bulk insert |
| Email/SMTP Sender | Notification | P2 | ⬜ | 알림 이메일 발송 |
| Slack/Teams Notifier | Notification | P2 | ⬜ | 채널 메시지 발송 |
| InfluxDB Writer | TimeSeries | P2 | ⬜ | 시계열 데이터 적재 |

### 3B. FTP/SFTP Collector 상세 스펙 🔥

산업 현장의 핵심 시나리오: **설비 → FTP/SFTP → 파이프라인**

```
설비/장비 → FTP 서버에 파일 생성 → Hermes가 감지 → Collect → Process → Export
```

#### Settings (프로세서 설정)
| Setting | Type | Description |
|---|---|---|
| host | string | FTP/SFTP 서버 주소 |
| port | number | 포트 (FTP:21, SFTP:22, FTPS:990) |
| protocol | select | FTP / FTPS / SFTP |
| username | string | 인증 사용자명 |
| password | password | 인증 비밀번호 |
| private_key | password | SFTP 키 인증 |
| passive_mode | boolean | FTP passive mode (default: true) |
| poll_interval | string | 폴링 주기 (예: 30s, 5m, 1h) |
| connection_timeout | number | 연결 타임아웃 (초) |
| max_connections | number | 최대 동시 연결 수 |

#### Recipe (운영 파라미터 — 버전 관리됨)
| Parameter | Type | Description |
|---|---|---|
| remote_path | string | 수집 대상 디렉토리 |
| recursive | boolean | 하위 폴더 재귀 탐색 |
| max_depth | number | 최대 탐색 깊이 (-1: 무제한) |
| file_filter_regex | string | 파일명 필터 (예: `.*\.csv$`) |
| path_filter_regex | string | 경로 필터 (예: `^/data/2026`) |
| ordering | select | NEWEST_FIRST / OLDEST_FIRST / NAME_ASC / NAME_DESC |
| discovery_mode | select | ALL / LATEST / BATCH / ALL_NEW |
| batch_size | number | BATCH 모드일 때 한 번에 가져올 파일 수 |
| completion_check | select | NONE / MARKER_FILE / SIZE_STABLE |
| marker_suffix | string | 완료 마커 파일 확장자 (예: .done, .complete) |
| stable_seconds | number | SIZE_STABLE 체크 대기 시간 |
| post_action | select | KEEP / DELETE / MOVE / RENAME |
| post_action_target | string | MOVE 대상 경로 또는 RENAME 접미사 |
| min_file_size | number | 최소 파일 크기 (bytes, 0=무제한) |
| max_file_age_hours | number | 최대 파일 나이 (시간, 0=무제한) |

#### 예외처리 시나리오 (빡빡하게)
```
Connection Failures:
  ├── 서버 연결 실패 → exponential backoff (1s, 2s, 4s, 8s... max 5m)
  ├── 인증 실패 → 즉시 STOP + Alert (재시도 무의미)
  ├── Connection refused → Circuit breaker OPEN (5분 후 HALF_OPEN)
  ├── DNS resolution 실패 → STOP + Alert
  └── TLS 핸드셰이크 실패 → STOP + Alert (인증서 문제)

Listing Failures:
  ├── Permission denied → SKIP + log warning (해당 디렉토리만)
  ├── Directory not found → STOP + Alert
  ├── Timeout → retry 3회 후 SKIP
  └── 서버 busy (421) → Retry-After 헤더 존중

Download Failures:
  ├── 다운로드 중 연결 끊김 → resume (부분 다운로드)
  ├── 파일이 다운로드 중 삭제됨 → SKIP + DLQ
  ├── 파일이 다운로드 중 변경됨 → 재다운로드
  ├── 체크섬 불일치 → retry 3회 후 DLQ
  ├── 디스크 공간 부족 → STOP + Alert
  └── 파일 크기 0 bytes → SKIP (설정 가능)

Post-Action Failures:
  ├── DELETE 실패 (permission) → log warning, 다음 폴링에서 재감지됨
  ├── MOVE 대상 디렉토리 없음 → 자동 생성 시도
  ├── MOVE 파일명 충돌 → timestamp 접미사 추가
  └── RENAME 실패 → log warning, 원본 유지
```

### 3C. 예외처리 프레임워크 (전체 모듈 공통)

```
모든 Connector 공통 패턴:
├── Connection Management
│   ├── Connection Pool (min/max/idle 설정)
│   ├── Health Check (주기적 ping)
│   ├── Auto-reconnect (configurable backoff)
│   └── Circuit Breaker (failure_threshold, recovery_timeout)
│
├── Error Classification
│   ├── TRANSIENT → auto-retry (네트워크, timeout)
│   ├── PERMANENT → STOP + Alert (인증, 설정 오류)
│   ├── THROTTLED → backoff + respect rate limits
│   └── UNKNOWN → DLQ + manual investigation
│
├── Retry Strategy
│   ├── Exponential backoff: base * 2^attempt (1s→2s→4s→8s)
│   ├── Jitter: ±25% randomization
│   ├── Max attempts: configurable (default: 5)
│   ├── Max delay: configurable (default: 5m)
│   └── Retry budget: 시간당 최대 재시도 횟수 제한
│
├── Dead Letter Queue
│   ├── 실패 데이터 격리 (원본 보존)
│   ├── 실패 사유 + stack trace 기록
│   ├── Manual replay / auto-replay 선택
│   └── DLQ 크기 제한 + 알림
│
└── Observability
    ├── Metrics: success/failure count, latency p50/p95/p99
    ├── Logs: structured JSON (correlation_id 포함)
    ├── Alerts: configurable threshold (실패율 > N%)
    └── Dashboard: Grafana 자동 생성
```

### 3D. 테스트 시나리오 확장 (목표: 300+ tests)

현재: 161 tests → 목표: 300+ tests

#### FTP/SFTP Collector Tests (60+)
```
Connection (10):
  - FTP/FTPS/SFTP 각각 connect/login 성공
  - 잘못된 credentials → 인증 실패
  - Connection refused → circuit breaker 작동
  - DNS 실패, TLS 실패, timeout
  - Passive mode fallback

Directory Traversal (15):
  - 단일/재귀 디렉토리 탐색
  - max_depth 제한 (0, 1, 3, -1)
  - 날짜 폴더 패턴 (yyyyMMdd, yyyy/MM/dd)
  - 정렬 (newest_first, oldest_first, name_asc)
  - 빈 디렉토리, 권한 없는 디렉토리
  - 심볼릭 링크 순환 방지
  - 10,000+ 파일 대규모 디렉토리

File Matching (15):
  - Regex 필터 (*.csv, *.json, 날짜 패턴)
  - Discovery mode (ALL, LATEST, BATCH, ALL_NEW)
  - 파일 크기 필터 (min/max)
  - 파일 나이 필터 (max_age)
  - Completion check (marker_file, size_stable)
  - Unicode 파일명

Download & Integrity (10):
  - 정상 다운로드 + checksum 검증
  - 대용량 (100MB+) 파일 스트리밍
  - 다운로드 중 연결 끊김 → resume
  - 다운로드 중 파일 변경/삭제
  - 0-byte 파일 처리

Post-Action (5):
  - KEEP/DELETE/MOVE/RENAME 각각
  - MOVE 충돌 해결 (timestamp suffix)

Error Recovery (5):
  - Circuit breaker open → half-open → close
  - DLQ 격리 + replay
  - Backpressure → 수집 일시정지 → 재개
```

#### Kafka Consumer/Producer Tests (30+)
```
Consumer (15):
  - 단일/다중 topic 구독
  - Consumer group 참여/탈퇴
  - Offset commit (auto/manual)
  - Partition rebalance 처리
  - Deserialization 실패 → DLQ
  - 메시지 크기 제한 초과
  - Broker 장애 → 자동 재연결
  - SSL/SASL 인증

Producer (15):
  - 단건/배치 발행
  - Partitioning (key-based, round-robin)
  - Ack 모드 (0, 1, all)
  - Serialization 실패
  - Broker 장애 → 버퍼링 + 재전송
  - 메시지 순서 보장
  - Idempotent producer
  - Transaction support
```

#### Export Connector Tests (30+)
```
S3 Upload (8):
  - 단건/배치 업로드
  - Multipart upload (대용량)
  - 파티셔닝 (date/source/custom)
  - Compression (gzip/snappy/zstd)
  - 권한 오류, 버킷 없음
  - 네트워크 실패 → retry

DB Writer (8):
  - INSERT/UPSERT/MERGE
  - Batch insert (1000건)
  - Schema mismatch → DLQ
  - Connection pool exhaustion
  - Deadlock → retry
  - Transaction rollback

Webhook (7):
  - POST 성공 (200/201/202)
  - 서버 오류 (500/502/503) → retry
  - Timeout → retry with backoff
  - Auth (Bearer, Basic, API Key)
  - Rate limit (429) → Retry-After
  - SSL 인증서 오류

Messaging (7):
  - AMQP publish + confirm
  - TIBCO RV publish
  - MQTT publish (QoS 0/1/2)
  - Connection lost → 버퍼링
```

#### End-to-End Pipeline Tests (20+)
```
Happy Path (5):
  - FTP → Anomaly Detection → S3
  - Kafka → Transform → DB
  - REST API → Filter → Kafka
  - File → Split → Merge → File
  - DB CDC → Transform → Webhook

Error Scenarios (10):
  - 중간 Step 실패 → 재처리
  - Source 장애 → 파이프라인 일시정지 → 복구
  - Export 장애 → DLQ → manual replay
  - Recipe 버전 변경 → 다음 실행부터 적용
  - Back-pressure → 수집 throttle
  - 다중 파이프라인 동시 실행
  - 파이프라인 비활성화 중 실행 완료 대기

Performance (5):
  - 1,000건 동시 처리 (throughput)
  - 10MB 파일 100개 파이프라인
  - 장시간 안정성 (1시간 연속)
```

### 3E. 기존 Phase 3 항목

#### Distributed Processing
- [x] Worker 노드 수평 확장 (in-process 시뮬레이션)
- [ ] Coordinator-Worker 아키텍처 (Orleans)
- [x] 작업 분배 + 리밸런싱 (round-robin)
- [x] Worker 장애 → 자동 재할당
- [ ] Split-brain 방지 (PostgreSQL advisory locks)

#### P2 Gaps
- [x] Authentication (JWT/OIDC)
- [x] RBAC (Viewer/Operator/Admin)
- [x] Audit Log
- [x] Data Preview
- [x] Content-Based Routing
- [x] Rate Limiting + Circuit Breaker

#### UI Enhancements (완료)
- [x] Pipeline Designer: Settings/Recipe 분리
- [x] 전역 Recipe Management 페이지
- [x] Recipe Diff Viewer (Git-style)
- [x] Connector Catalog (drag-and-drop)
- [x] Collect/Process/Export 카테고리 리네이밍

---

## Phase 4: Exit-Ready (+3 months)

- [ ] Multi-tenancy (Workspace 격리)
- [ ] Plugin Marketplace (내부/외부)
- [ ] Pipeline Git Integration
- [ ] Environment Promotion (dev → staging → prod)
- [ ] SLA Monitoring + Alerting
- [ ] SOC2 readiness, GDPR
- [ ] Documentation site, CLI, Terraform Provider

---

## Development Workflow

### Branch Strategy
```
main          ← 안정 릴리스
├── develop   ← 개발 통합
│   ├── feature/xxx  ← 기능 개발
│   ├── fix/xxx      ← 버그 수정
│   └── test/xxx     ← 테스트 추가
└── release/x.y.z    ← 릴리스 준비
```

### PR Checklist
```
□ 기존 테스트 전부 통과
□ 새 기능에 대한 테스트 코드 포함
□ 커버리지 하락 없음
□ lint 통과
□ 보안 검사 통과 (no hardcoded secrets)
□ ROADMAP.md 업데이트 (해당 시)
```

---

## Changelog

### v0.3.0 (2026-03-16) — Phase 3
- Collect/Process/Export 카테고리 리네이밍 (ALGORITHM→PROCESS, TRANSFER→EXPORT)
- 전역 Recipe Management 페이지 (버전 타임라인, diff, 파이프라인 영향 범위)
- Pipeline Designer: Settings/Recipe 분리 (Settings=프로세서 설정, Recipe=전역 관리)
- Sidebar 네비게이션에 Recipes 추가
- FTP/SFTP Collector 상세 스펙 + 예외처리 시나리오
- 커넥터 확장 로드맵 (37+ connectors 목표)
- 테스트 시나리오 확장 계획 (300+ tests 목표)

### v0.2.0 (2026-03-15) — Phase 2
- NiFi-style processor config: Settings/Recipe/History tabs
- 8 native plugins (REST API, File Watcher, Passthrough, File Output + 4 NiFi-equivalent)
- FTP/SFTP collector with recursive traversal, regex filters
- Recipe Diff Viewer (Git-style side-by-side)
- 161 tests across collection, matching, traversal

### v0.1.0 (2026-03-15) — Phase 0/1
- Initial project setup (Python prototype + React UI)
- Architecture design documents
- DB schema (19 tables)
- Plugin system (6 built-in plugins)
- 90 test scenarios
