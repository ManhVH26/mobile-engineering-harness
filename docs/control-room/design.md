# Control Room — thiết kế (Phase 1, investigate-only)

> Trạng thái: **DRAFT — chờ owner duyệt.** Chưa implement. Doc này mô tả kiến trúc một **trang HTML local / project** làm **control surface** cho harness spec→code pipeline chạy **bên dưới bằng Orca** (Orca spawn agent + tạo worktree cho mỗi đơn vị việc). Owner duyệt + trả lời open questions xong mới sang Phase 2.

Tác giả: worker Orca (task Control Room). Ngày: 2026-11-27. Harness version hiện tại: 0.23.0.

---

## 1. Mục tiêu (từ owner)

Một trang web HTML **duy nhất / project** để owner:

1. **Theo dõi tiến độ** pipeline spec→code khi nó chạy (full app build hoặc update 1 feature): đang ở stage/phase nào, agent/role nào chạy, status, link log/artifact.
2. **Trả lời các Q&A gate** (approval gate, câu hỏi ambiguity, quyết định Tech Lead/PM, brief READY/BLOCKED…) **ngay trên trang** — không phải nhảy giữa nhiều cửa sổ/terminal Orca.
3. **Bug panel** sau khi build xong: fetch bug từ Jira (self-hosted `jira.apero.vn`) cho project; owner **kéo 1 bug card vào vùng "Fix"** → trang kích hoạt bug-fix skill (mode `note` cho 1 bug, `batch` cho nhiều) → tiến độ + kết quả PR hiện lại trên cùng trang.
4. Tổng: **1 project = 1 trang**, điều khiển toàn bộ 1 phase/project từ đó.

**Ràng buộc owner chốt thêm (clarification 2026-11-27):** surface **duy nhất** là trang HTML. **Bên dưới bắt buộc là Orca** làm orchestration: Orca spawn agent và **tạo một worktree cho mỗi đơn vị việc** (bắt buộc). Trang → local server → **orca CLI** (`orca orchestration worker-start`, `orca worktree ps`, `orca orchestration send`, `orca orchestration reply`…) để start/nhắn worker trong worktree mới. **Không** thiết kế quanh việc chạy `claude -p` trần bên ngoài Orca.

---

## 2. Harness hoạt động hôm nay (khảo sát)

### 2.1 Pipeline spec→code & nơi state đang nằm

| Lớp | Skill / Workflow entry | State artifact đang ghi ra repo |
|---|---|---|
| Input (spec+design → brief) | `business-prepare-feature` (5 phase: fetch→analyze spec→analyze design→reconcile→validate), workflow `prepare-feature-brief` | `briefs/<slug>/` — `brief.yaml` (manifest máy đọc), `requirements.md`, `design.md`, `acceptance-criteria.md`, `issues.md`, `assets/sources/`. Blocker = `issues[severity=blocker]` chặn implement cho tới khi human review. Brief được validate thành **READY / BLOCKED / FAILED**. |
| Feature full-flow | `feature` (→ `references/single.md`, spawn `orchestrator`, chain 8 stage Product Analyst→PM→Designer→Tech Lead→Architect→review gate→Coder→Reviewer+QA→Release), workflow `feature-development.md` (5 stage INSPECT→PLAN→IMPLEMENT→VERIFY→REPORT) | `plans/<YYMMDD-HHMM>-<slug>/plan.md` (1-page plan), `plans/handoff/<slug>/<from>-to-<to>.md` (handoff doc giữa agent, có `Status: ready/blocked/needs-context`), `plans/reports/*.md` (report cuối, có `Status: VERIFIED/VERIFIED_WITH_LIMITATIONS/BLOCKED/FAILED`). |
| Parallel features | `feature --parallel`, workflow `parallel-feature-development.md` | như trên + N lane worktree. |
| Bug-fix note (1 bug) | `bug-fix` mode `note` (`/bug-note`), 1 worker nền = 1 worktree = 1 PR | state ở `<git-common-dir>/bug-fix/queue.json` qua `scripts/bug_queue.py` (`BUG-NNN`, status queued/investigating/waiting/done…), evidence ở `plans/reports/bugs/<BUG-ID>-<slug>/`, hàng chờ test tay `plans/reports/bugs/DEVICE-TEST-QUEUE.md`. |
| Bug-fix batch (N bug) | `bug-fix` mode `batch` (`/bug-fix-orchestrator`), scout 1 lần → lane song song | `plans/bugfix-batch-<id>/` qua `scripts/bfo` (`bfo_state.py`): `manifest.json`, `state.json`, `bugs.json`, `scout.json`, `plan.json`, `context/…`, `evidence/<KEY>/`. |
| spec-to-release (pipeline 4 phase mới hơn) | `spec-to-release:*` skills | `.spec-to-release/` + `plan.json`, `grounded-tasks.json`, `test-report.json`, `.spec-to-release/reports/`. |

**Nhận xét quan trọng:** harness **đã ghi state ra file** ở mọi lớp (brief.yaml, plan.md, handoff, reports, bfo state.json, bug queue.json). Control Room MVP có thể **đọc trực tiếp các file này** để dựng progress mà **chưa cần hook gì**. Hook event/gate (mục 6) là lớp nâng cấp cho live-progress mịn hơn + gate 2 chiều.

### 2.2 Human gate đang xảy ra ở đâu

- **Không** có cơ chế gate tập trung. Gate hiện là **agent "surface user / stop và hỏi"** bằng prose trong chat (xuyên suốt `feature-development.md` "Blocker conditions → stop và hỏi user", CLAUDE.md "Scope guard → MUST raise user", bug-fix "NEEDS_INPUT → relay câu hỏi cho user").
- `AskUserQuestion` chỉ dùng ở vài skill input (`product-spec-creator`, `harness-init`) — không phải ở pipeline code.
- Gate review (Tech Lead APPROVE/REQUEST_CHANGES, brief READY/BLOCKED) hiện là agent ghi verdict vào handoff/report rồi chờ người đọc.
- Trong Orca, worker con raise gate bằng **`orca orchestration ask`** (type `question`) → vào inbox của coordinator; coordinator trả lời bằng **`orca orchestration reply --id <message_id>`**. Đây là channel gate "native" của Orca nhưng gắn với một coordinator session.

**Hệ quả thiết kế:** Control Room cần **chuẩn hoá gate** thành một contract file + (tuỳ chọn) bắc cầu sang orca mail, để mọi gate (bất kể agent chạy trong Claude Code hay Orca terminal) đều hiện lên trang và nhận được câu trả lời.

### 2.3 Orca orchestration CLI (nền bên dưới — bắt buộc dùng)

Từ `orca skills get orchestration` + `orca skills get orca-cli`:

- **Spawn 1 worker + worktree mới / đơn vị việc:**
  - Supervised (có mail báo về): `orca orchestration worker-start --environment local --spec "<task>" --worktree new-child --name <short> --agent <agent>` → chạy worker trong **worktree con mới**, report về coordinator bằng `worker_done` / `ask` / `escalation`.
  - Handoff (không cần mail về): `orca worktree create --name <n> --parent-worktree active --agent <agent> --prompt "<brief>" --json` → tạo checkout + start agent; đọc tiến độ bằng `orca agent read <id> --json`.
- **Nhắn worker:** `orca orchestration send --to dispatch:<id> --type question|dispatch --subject --body` (hoặc `--to <terminal handle | orca_session_id:<chat>>`).
- **Trả lời câu hỏi worker:** `orca orchestration reply --id <message_id> --body "<answer>"`.
- **Đọc worker / liveness:** `orca orchestration worker-read --dispatch <id>`, `orca agent read <id>`, `orca worktree ps --json`, `orca worktree list --json`, `orca orchestration inbox --terminal run:<run_id>`.
- **Port dev server:** `orca ports --json`.
- **Lưu ý:** `worker-start` + inbox/reply gắn với **danh tính coordinator** (một Orca agent session có `orca_session_id`). Một server python trần **không có** session id → **không** tự làm coordinator-of-record cho supervised worker. Hai cách giải quyết ở mục 4.

---

## 3. Governance (phải tôn trọng)

| Rule | Nguồn | Tác động lên Control Room |
|---|---|---|
| **Dashboard/infra = OUT of scope upstream** | `CONTRIBUTING.md §Scope boundary`: "OUT of scope upstream (product overlay thay): Infrastructure (CI/CD, VPS, device farm, **dashboard**)" | Control Room là **tooling/infra**, không phải constitution/rule. ⇒ Đặt nó dưới dạng **skill opt-in + scripts** (tooling), **không** đụng constitution/ADR. Việc nó sống trong repo upstream này hay tách overlay là **open question #1** cho owner. |
| **Permission level L0–L3 + protected baseline** | `knowledge/meta/harness-governance` (KB) | Thêm Control Room = thay đổi **skill/workflow/script = L2** (review độc lập), **không** chạm L3 (constitution/ADR). Hook vào skill orchestration phải **additive + optional + backward-compatible** (overlay không bật Control Room vẫn chạy y như cũ). |
| **Versioning / CHANGELOG / PR flow** | `CONTRIBUTING.md §Release`, `CHANGELOG.md` (hiện `[Unreleased]`, latest `0.23.0`) | Feature mới → **minor bump 0.24.0** + entry CHANGELOG; nhánh `feat/<name>`, Conventional Commits, PR có Scope/Testing/Breaking/Migration; squash merge. |
| **harness-maintenance** | `skills/harness-maintenance`, `agents/harness-guardian.md` | Thay đổi vào chính harness nên đi qua guardian mindset / audit; giữ change nhỏ, có evidence. |
| **python3 stdlib** | `README.md` prerequisites (git, python3, PyYAML) | Server + script dùng **python3 stdlib** (prefer zero-dep), đúng baseline harness. PyYAML đã có sẵn để đọc `brief.yaml`. |

---

## 4. Kiến trúc đề xuất

### 4.1 Tổng quan

```
┌──────────────────────────────────────────────────────────────────────┐
│  Trang HTML (1 / project)  —  surface DUY NHẤT                         │
│  [Pipeline progress] [Gate inbox] [Bug panel + drop-zone "Fix"]        │
└───────────────┬──────────────────────────────▲───────────────────────┘
      HTTP + SSE │ (fetch actions / stream events)│ events, gates, bugs
                 ▼                                │
┌──────────────────────────────────────────────────────────────────────┐
│  Local server (python3 stdlib, http.server)  —  1 process / project    │
│  • serve trang + API  • đọc state files + events.jsonl (tail→SSE)      │
│  • ghi file answer cho gate  • shell ra `orca …` để spawn/nhắn worker  │
└───────┬───────────────────────────┬───────────────────────────────────┘
        │ shell orca CLI            │ đọc/ghi file (contract)
        ▼                           ▼
┌───────────────────┐   ┌───────────────────────────────────────────────┐
│  ORCA runtime     │   │  .harness/run/<run-id>/                        │
│  worker-start /   │   │   state.json · events.jsonl · gates/<id>.json │
│  worktree create  │◄──┤   gates/<id>.answer.json · bugs/<project>.json│
│  → 1 worktree /   │   │  (contract chung cho mọi agent, file-based)   │
│    đơn vị việc     │   └───────────────────────────────────────────────┘
└───────────────────┘             ▲ emit events / raise gate / block
        │ spawn                    │
        ▼                          │
   Orca worker agents (orchestrator / coder / bug-fixer / …) mỗi cái 1 worktree
```

### 4.2 Hai vai trò của server với Orca — chọn mô hình

Vì server trần không có `orca_session_id`, có 2 mô hình spawn:

- **Mô hình A — Coordinator agent / project (ĐỀ XUẤT cho tầm nhìn đầy đủ).** Mỗi project có **một Orca agent "Control Room coordinator"** sống lâu. Server **không** tự orchestrate; nó chỉ `orca orchestration send --to <coordinator>` các lệnh của trang (start build, answer gate, fix bug). Coordinator:
  - chạy `orca orchestration worker-start --worktree new-child` cho **mỗi đơn vị việc** (đúng yêu cầu owner: Orca spawn + worktree/đơn vị),
  - nhận `ask`/`escalation`/`worker_done` của worker,
  - **mirror** mọi tiến độ + gate pending vào `.harness/run/<run-id>/` để trang đọc,
  - khi trang trả lời gate → server ghi answer file **và** `send` cho coordinator → coordinator `reply` cho đúng worker.
  - Ưu: đúng mô hình supervised của Orca (mail, DAG, escalation). Nhược: cần 1 agent coordinator luôn chạy / project.
- **Mô hình B — Server "mỏng" + file-gate (ĐỀ XUẤT cho MVP).** Server tự `orca worktree create --parent-worktree active --agent <agent> --prompt "<spec> + đọc run-dir <path>"` cho mỗi đơn vị việc (handoff CLI mà caller thường chạy được), rồi đọc tiến độ qua `orca agent read` + `orca worktree ps` + `events.jsonl`. Gate **không** đi qua orca mail (vì không có coordinator) mà đi qua **file-gate** (mục 5). Ưu: không cần agent coordinator; đơn giản, robust. Nhược: mất lớp supervision/mail của Orca (chỉ có liveness qua `worktree ps`).

> **Khuyến nghị:** MVP theo **B** (nhanh, ít phụ thuộc), nhưng **thiết kế contract file-based ngay từ đầu** để nâng lên **A** không phải đập đi. **File-gate là backbone chung cho cả A và B** (A thêm orca mail như lớp phủ). Chốt A hay B là **open question #2**.

### 4.3 Server (python3 stdlib)

- `http.server` + `ThreadingHTTPServer`, bind `127.0.0.1:<port>` (chỉ localhost). Port ghi vào `.harness/run/control-room.port` + log; Orca thấy qua `orca ports --json`.
- Endpoints (JSON):
  - `GET /` → trang HTML (một file self-contained, inline CSS/JS, không CDN bắt buộc).
  - `GET /api/state` → snapshot `state.json` + danh sách gate pending + bug list.
  - `GET /api/events` → **SSE** stream (tail `events.jsonl`), đẩy event mới cho trang.
  - `POST /api/gate/<gate-id>/answer` → ghi `gates/<gate-id>.answer.json`.
  - `POST /api/build` → start pipeline (spawn qua orca, mục 4.2).
  - `POST /api/bugs/refresh` → trigger fetch Jira (mục 7).
  - `POST /api/bugs/fix` → drag→Fix: spawn bug-fix note/batch (mục 8).
- **Chỉ đọc/ghi trong `.harness/run/` + shell `orca`**; không giữ business logic nặng — "mắt + tay", đúng tinh thần leader-không-tự-làm của harness.

---

## 5. State & Event contract (`.harness/run/<run-id>/`)

Một thư mục / run (build hoặc đợt bug-fix). `run-id` = `build-<slug>-<ts>` hoặc `bugfix-<id>`.

```
.harness/run/<run-id>/
├── state.json              # snapshot: run, stages[], workers[], updated_at
├── events.jsonl            # append-only, mỗi dòng 1 event (nguồn cho SSE)
├── gates/
│   ├── <gate-id>.json          # gate pending (do agent ghi khi cần hỏi)
│   └── <gate-id>.answer.json   # câu trả lời (do server ghi khi owner bấm)
└── bugs/<project>.json     # bug list fetch từ Jira (Bug panel)
```

**`state.json`** (ví dụ rút gọn):
```json
{"run_id":"build-book-detail-261127","kind":"feature","slug":"book-detail",
 "status":"running","updated_at":"2026-11-27T10:00:00+07:00",
 "stages":[{"id":"inspect","name":"Inspect","agent":"architect","status":"done"},
           {"id":"plan","name":"Plan","agent":"architect","status":"running",
            "artifact":"plans/261127-1000-book-detail/plan.md"}],
 "workers":[{"name":"architect","worktree":"repo-1::/…/book-detail","orca_dispatch":"ctx_…","status":"working"}],
 "gates_pending":["g-plan-review-1"]}
```

**`events.jsonl`** — mỗi event: `{ts, run_id, type, stage?, worker?, level, msg, ref?}`; `type ∈ {stage_start, stage_done, worker_spawn, worker_done, gate_raised, gate_answered, artifact, log, error}`. Server **chỉ append**, đọc để stream; không mutate lịch sử.

**Gate file** `gates/<gate-id>.json`:
```json
{"id":"g-plan-review-1","run_id":"…","raised_by":"architect","raised_at":"…",
 "kind":"approval","title":"Duyệt plan book-detail?",
 "question":"Plan đụng 8 file, thêm UseCase mới. APPROVE để Coder bắt đầu?",
 "options":[{"id":"approve","label":"APPROVE"},{"id":"request_changes","label":"REQUEST_CHANGES"},{"id":"escalate","label":"ESCALATE PM"}],
 "allow_freeform":true,"context_refs":["plans/261127-1000-book-detail/plan.md"],"status":"pending"}
```
**Answer file** `gates/<gate-id>.answer.json`: `{"gate_id":"…","option_id":"approve","note":"ok, giữ UseCase","answered_at":"…","answered_by":"owner"}`.

### 5.1 Cơ chế gate 2 chiều (trả lời owner clarification)

1. Agent (bất kể trong Claude Code hay Orca terminal) tới điểm cần hỏi → **ghi** `gates/<id>.json` (status=pending) + **append** event `gate_raised` → rồi **block** bằng helper stdlib `gate_wait.py <run-dir> <gate-id>` (poll tồn tại `<id>.answer.json`, timeout + backoff; hoặc watch mtime). Agent **không** tự quyết, đúng Scope guard của CLAUDE.md.
2. Server phát event `gate_raised` qua SSE → trang render card gate (tiêu đề, câu hỏi, option, link artifact).
3. Owner bấm option (hoặc gõ freeform) → `POST /api/gate/<id>/answer` → server ghi `<id>.answer.json` + append `gate_answered`.
4. `gate_wait.py` thấy answer → trả JSON cho agent → agent đọc `option_id`/`note` và tiếp tục.
5. **Mô hình A (bonus):** worker raise gate bằng `orca orchestration ask` → coordinator nhận mail, **đồng thời** coordinator ghi gate file (để hiện lên trang) và khi owner trả lời, coordinator `orca orchestration reply --id <msg> --body <note>` cho worker. File-gate là chuẩn chung; orca mail là đường supervised song song.

> File-gate hoạt động **kể cả khi agent chạy trong Orca terminal không có coordinator** (mô hình B) — đây là lý do chọn file làm backbone.

---

## 6. Hook vào skill/workflow (optional, backward-compatible)

Nguyên tắc: **thêm, không sửa hành vi cũ**. Nếu biến môi trường `HARNESS_RUN_DIR` **không set** → mọi hook là no-op, pipeline chạy y như hiện tại.

| Điểm hook | Skill/workflow | Thêm gì | Mức |
|---|---|---|---|
| Stage start/done | `workflows/feature-development.md` 5 stage, `feature/references/single.md` sau mỗi stage | 1 dòng gọi `emit.py stage_start/stage_done <id>` nếu `HARNESS_RUN_DIR` set | L2 |
| Handoff ready/blocked | CLAUDE.md handoff doc flow, `orchestrator.md` | khi ghi handoff → append event + nếu `Status: blocked` → raise gate | L2 |
| Review/approval gate | Tech Lead review gate, brief READY/BLOCKED (`business-validate-brief`), Scope guard (CLAUDE.md "MUST raise user") | thay "surface user bằng prose" → `raise_gate.py` + `gate_wait.py` | L2 |
| Report done | `feature-development.md` Stage 5, `plans/reports/*` | append `artifact` + `worker_done` event | L2 |
| Bug-fix note/batch tiến độ | `bug-fix` mode-note (worker report), mode-batch (`bfo_state.py` lane/jira-sync) | emit event khi status đổi (đã có state.json/queue.json → map sang events) | L2 |

Helper scripts (python3 stdlib) dùng chung: `emit.py` (append event + cập nhật state.json), `raise_gate.py`, `gate_wait.py`. Đặt ở `scripts/control_room/`.

**Backward compat:** overlay cũ không có `.harness/run/` + không set `HARNESS_RUN_DIR` → hook thoát ngay, 0 ảnh hưởng. Đây là điều kiện để qua review L2 + CONTRIBUTING "overlay cũ vẫn work".

---

## 7. Jira fetch (Bug panel)

**Ràng buộc đã khảo sát:** harness truy cập Jira **chỉ qua `jira` MCP** (`jira_search`, `jira_get_issue`, `jira_get_sprint_issues`, `jira_download_attachments`…). **Không** có REST token/cred nào trong repo (xác nhận: không có `.mcp.json`/`JIRA_URL` trong repo; creds nằm ở cấu hình MCP của Claude Code/Orca). ⇒ **Server python stdlib KHÔNG tự gọi Jira được** (không có MCP, không có token — và không được hardcode/commit token).

**Cách lấy bug (đề xuất):** server **không** fetch Jira trực tiếp. Khi owner bấm "Refresh bugs" → server spawn **một Orca agent ngắn** (`orca worktree create --agent general-purpose --prompt "Dùng jira MCP, chạy jira_search(jql=<…>, fields=summary,description,status,priority,labels,components,issuetype), normalize như bug-fix/references/intake-and-context.md, ghi .harness/run/<run-id>/bugs/<project>.json. Không chép email/tên reporter."`). Agent này tái dùng đúng jira MCP + đúng quy tắc normalize của `intake-and-context.md §1`. Server đọc `bugs/<project>.json` → trang render card.

- **Auth/source:** tái dùng cấu hình `jira` MCP sẵn có của owner (jira.apero.vn). **Không** hardcode, **không** commit token; `bugs/<project>.json` nằm trong `.harness/run/` (khuyến nghị gitignore).
- JQL mặc định / project lấy từ config project (vd `project = <KEY> AND issuetype = Bug AND statusCategory != Done`), cho owner sửa trên trang.
- Alternative (open question #3): nếu owner muốn server tự fetch không qua agent → cần một cách lấy Jira token an toàn (vd đọc từ env/`~/.netrc` do owner tự set, không commit) + gọi REST `rest/api/2/search`. Mặc định đề xuất **đi qua MCP/agent** để không đụng token.

---

## 8. Drag bug → "Fix" → bug-fix skill

1. Owner kéo 1 bug card (hoặc chọn nhiều) thả vào drop-zone "Fix".
2. `POST /api/bugs/fix {keys:[…], mode:"note"|"batch"}`.
3. Server spawn qua Orca (đúng yêu cầu Orca-orchestration + worktree/đơn vị):
   - **1 bug (`note`)**: `orca orchestration worker-start --worktree new-child --name fix-<KEY> --agent bug-fixer --spec "<brief note-worker: bug text từ bugs.json, run-dir, emit event, raise gate nếu NEEDS_INPUT>"` (mô hình A), hoặc `orca worktree create --agent bug-fixer --prompt …` (mô hình B).
   - **≥2 bug (`batch`)**: spawn 1 worker leader `bug-fix` mode batch (nó tự scout 1 lần + lane worktree song song như hiện tại), truyền run-dir để emit event/gate.
4. Worker fix → mở **draft PR** → `bug-reviewer` APPROVE → `gh pr ready` (giữ nguyên flow bug-fix hiện tại). Worker emit các event `worker_spawn/log/artifact/worker_done` + append **PR URL** vào `state.json`.
5. Trang hiện tiến độ từng bug + badge PR (draft/ready/merged) + link. Câu hỏi của worker (NEEDS_INPUT) → gate trên trang (mục 5.1).

---

## 9. MVP vs sau

**MVP (Phase 2 đợt 1):**
- Server python3 stdlib + 1 trang HTML self-contained; chạy `/project`.
- **Progress read-only** từ state files **có sẵn** (brief.yaml, plan.md, handoff/*, reports/*, bfo `state.json`, bug `queue.json`) — chưa cần hook, đã xem được pipeline.
- **File-gate 2 chiều** + `raise_gate.py`/`gate_wait.py` + hook gate ở **1–2 điểm** (Tech Lead plan-review gate, brief READY/BLOCKED) để chứng minh luồng Q&A trên trang.
- **Bug panel**: refresh Jira qua agent ngắn + render card + drag→Fix spawn bug-fix **note** 1 bug, hiện PR URL.
- Mô hình **B** (server mỏng + `orca worktree create --agent`).

**Sau MVP:**
- `events.jsonl` + SSE live mịn; hook emit đủ 5 stage.
- Mô hình **A** (coordinator agent + supervised worker-start + orca mail bridge cho gate).
- Bug batch (nhiều bug, lane song song), sync Jira status.
- Multi-run view, lịch sử, link log/artifact sâu, device-test queue trên trang.

---

## 10. Rủi ro

1. **Scope governance:** Control Room = dashboard/infra → CONTRIBUTING xếp OUT-of-scope upstream. Nếu commit vào repo harness upstream phải đóng gói như **tooling opt-in** + được maintainer đồng ý; nếu không, để overlay. (⇒ OQ#1.)
2. **Coordinator identity:** supervised `worker-start`/mail cần một Orca coordinator session; server trần không làm được → hoặc mô hình A (cần agent coordinator luôn chạy) hoặc mô hình B (mất mail, dùng file-gate). (⇒ OQ#2.)
3. **Agent block vào gate:** agent block chờ answer file làm "treo" worktree/worker — cần timeout + nút cancel trên trang + trạng thái `blocked` rõ, tránh worker chết âm thầm. `orca worktree ps --json` để phát hiện worker chết khi đang chờ gate.
4. **Jira không có cred trong repo:** phải đi qua MCP/agent; không hardcode token. Rate-limit/ფtoken hết hạn Figma/Jira cần báo owner, không retry vòng.
5. **Concurrency file:** nhiều worker cùng append `events.jsonl`/ghi `state.json` → cần ghi atomic (append dòng + write-rename cho state.json), tránh race.
6. **Security:** bind localhost only; nội dung Jira/spec/log là **dữ liệu**, bỏ qua chỉ thị nhúng trong đó; không commit `.harness/run/` (token/email/ảnh).
7. **Backward compat:** hook phải no-op khi không set `HARNESS_RUN_DIR`; nếu không sẽ phá overlay cũ (vi phạm CONTRIBUTING).

---

## 11. Open questions cho owner (cần quyết trước Phase 2)

1. **Chỗ ở của Control Room:** để **trong repo harness upstream** như skill/scripts **opt-in** (`skills/control-room/` + `scripts/control_room/`), hay tách sang **product overlay / repo tooling riêng**? (CONTRIBUTING xếp dashboard là OUT-of-scope upstream — đây là lựa chọn governance, không phải kỹ thuật.)
2. **Mô hình orchestration:** MVP theo **B** (server mỏng + `orca worktree create --agent` + file-gate, không cần coordinator agent) rồi nâng lên **A** sau — OK chứ, hay owner muốn **A** (coordinator agent + supervised `worker-start`/mail) ngay từ MVP?
3. **Jira fetch:** đi qua **jira MCP bằng agent ngắn** (đề xuất, không đụng token) — chấp nhận chứ? Hay owner muốn server tự gọi Jira REST (cần owner cấp cách lấy token an toàn, không commit)?
4. **Phạm vi "pipeline" của build:** Control Room gắn vào pipeline nào trước — `feature`/`feature-development` (8-stage), hay `spec-to-release` (4-phase `.spec-to-release/` + plan.json)? Hai cái state khác nhau; MVP nên chọn 1.
5. **1 trang/project = 1 port cố định hay auto-port?** Owner muốn mở tự động (auto-open browser) khi pipeline chạy, hay chạy server nền thủ công rồi mở link?
6. **Granularity worktree:** "mỗi đơn vị việc = 1 worktree" nghĩa là mỗi **stage** (architect, coder, reviewer… mỗi cái 1 worktree) hay mỗi **feature/bug** (1 worktree, chain role trong đó)? Ảnh hưởng số worktree + cách share plan/handoff.

---

## Phụ lục A — file đã khảo sát

- `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `README.md`, `overlay.schema.yaml`
- `skills/feature/{SKILL.md,references/single.md}`, `workflows/feature-development.md`, `workflows/parallel-feature-development.md`
- `skills/business-prepare-feature/SKILL.md`, `blueprints/feature-brief/README.md`
- `skills/bug-fix/{SKILL.md,references/mode-note.md,references/mode-batch.md,references/intake-and-context.md}`
- `skills/harness-maintenance/SKILL.md`, `knowledge/meta/harness-governance` (KB)
- `orca skills get orchestration`, `orca skills get orca-cli`
- State hiện có: `plans/`, `plans/handoff/`, `plans/reports/`, `briefs/`, `plans/bugfix-batch-<id>/`, `<git-common-dir>/bug-fix/queue.json`
