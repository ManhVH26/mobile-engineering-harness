# Control Room

Một **trang HTML local / project** làm **control surface** cho harness spec→code pipeline chạy **bên dưới bằng Orca**. Từ một trang duy nhất owner: xem tiến trình pipeline, trả lời Q&A gate ngay trên trang, và kéo bug Jira vào ô **Fix** để spawn bug-fix.

> **Standalone tooling.** Thư mục này **không** phụ thuộc vào, và **không** sửa, bất kỳ skill/constitution nào của harness. Harness chạy y hệt dù có hay không Control Room. Nó chỉ **đọc** file state của project và **shell** lệnh `orca`. Có thể tách ra repo riêng bất cứ lúc nào (`git subtree split --prefix tools/control-room`). Đặt ở đây để đi chung một PR (CONTRIBUTING xếp dashboard là out-of-scope upstream → giữ tách biệt, không nhét vào `skills/`, `constitution/`, `agents/`).

## Yêu cầu

- `python3` ≥ 3.9 (chỉ **stdlib**, không cài gì thêm).
- `orca` CLI (cho spawn build / bug-fix / fetch Jira). Không có orca vẫn xem được tiến trình + gate (phần đọc state).
- Jira lấy qua **jira MCP** của Orca/Claude Code (agent ngắn) — **không** hardcode/commit token, server **không** tự gọi REST.

## Chạy

```bash
cd tools/control-room
python3 run.py --project /đường/dẫn/tới/repo-project
# mặc định: project = thư mục hiện tại, auto chọn port rảnh, auto mở browser
```

Cờ:
- `--project <path>` — repo project cần theo dõi (default: cwd).
- `--port N` — mặc định `0` = auto port rảnh.
- `--no-open` — không tự mở browser.
- `--jira-project KEY` — project key Jira mặc định cho Bug panel (hoặc env `CONTROL_ROOM_JIRA_PROJECT`).
- Agent spawn mặc định `claude` (đổi bằng env `CONTROL_ROOM_AGENT`).

Port đang chạy được ghi ra `<project>/.harness/run/control-room.port` (và `orca ports --json` thấy).

## Ba luồng MVP

### (a) Xem tiến trình 1 run feature
Trang đọc state theo 2 nguồn:
1. **Contract** (live): `<project>/.harness/run/<run-id>/state.json` + `events.jsonl` + `gates/` — do worker ghi qua `bin/emit.py`.
2. **Fallback** (read-only): quét artifact harness đã có sẵn — `plans/<date>-<slug>/plan.md` (dòng `Status:`), `phase-*.md`, `plans/reports/*.md`, `briefs/<slug>/` — nên thấy tiến trình cả khi chưa wire hook nào.

### (b) Gate 2 chiều trên trang
Worker tới điểm cần owner quyết → ghi gate + **block**:
```bash
GID=$(python3 tools/control-room/bin/raise_gate.py <run_dir> --id g-plan-1 --kind approval \
      --title "Duyệt plan?" --question "Plan đụng 8 file. APPROVE?" \
      --option approve:APPROVE --option request_changes:"REQUEST CHANGES" --allow-freeform \
      --context-ref plans/.../plan.md)
ANS=$(python3 tools/control-room/bin/gate_wait.py <run_dir> "$GID" --timeout 7200)
# đọc $ANS (JSON {option_id, note}) rồi tiếp tục theo lựa chọn owner
```
Gate hiện trên trang → owner bấm option (±ghi chú) → `gate_wait` nhả → worker chạy tiếp. Timeout (exit 2) mới fallback hỏi chat.

### (c) Bug panel + kéo-thả Fix
- Nhập project key → **Refresh** → server spawn agent ngắn dùng jira MCP, ghi `.harness/run/bugs/<key>.json` → card hiện lên.
- Kéo 1 bug card vào ô **Fix** → server spawn `/bug-fix` (mode `note` cho 1 bug) qua `orca worktree create --agent` → tiến độ + PR hiện trên cùng trang.

## Thử nhanh không cần Orca (demo offline cho a + b)

```bash
cd tools/control-room
python3 examples/seed_demo.py --project /tmp/cr-demo          # tạo 1 run demo + 1 gate + bug mẫu
python3 run.py --project /tmp/cr-demo                          # mở trang, chọn run "book-detail DEMO"
# ở terminal khác, mô phỏng worker bị chặn bởi gate rồi chạy tiếp khi owner trả lời:
python3 examples/seed_demo.py --project /tmp/cr-demo --wait
# → lên trang bấm APPROVE ở card gate → worker nhả block, pipeline chạy tới DONE + có PR
```

## Verification

```bash
cd tools/control-room
python3 -m unittest discover -s tests -v     # 12 unit test: store/emit/gate round-trip/fallback/orca-cmd
```

Smoke test thủ công (server + API, không cần Orca): xem mục demo offline ở trên; đã kiểm `/api/config`, `/api/runs`, `/api/run`, `/api/bugs`, `/api/gate/answer`, và SSE `/api/events` chạy đúng.

Spawn thật (build / bug-fix / fetch Jira) cần Orca + jira MCP đang chạy; các lệnh `orca` được dựng trong `cr/orca.py` và chỉ chạy khi owner bấm nút trên trang.

## Kiến trúc (tóm tắt)

```
Trang HTML ──HTTP/SSE──► server.py ──┬── đọc .harness/run/<id>/ (state/events/gates) + fallback plans/briefs
  (1 surface)                        ├── ghi gates/<id>.answer.json  (trả lời gate)
                                     └── shell `orca worktree create --agent …`  (spawn worker/worktree)
worker (Orca agent, 1 worktree/feature|bug) ── emit.py / raise_gate.py / gate_wait.py ──► .harness/run/<id>/
```

- **Điều phối = Orca**: server mỏng shell `orca` CLI; 1 worktree / feature hoặc / bug (chain role bên trong), **không** ép mỗi stage 1 worktree, **không** coordinator-agent ở MVP.
- **Gate = file-based 2 chiều**: hoạt động kể cả khi agent chạy trong Orca terminal không có coordinator.

## File

```
tools/control-room/
├── run.py                 # entrypoint
├── cr/                    # server, runstate reader, orca cmd builder, gate answerer
├── bin/                   # emit.py / raise_gate.py / gate_wait.py (worker gọi, self-contained)
├── web/index.html         # 1 trang self-contained (no CDN)
├── examples/seed_demo.py  # demo offline a+b
└── tests/                 # unittest stdlib
```

## Bảo mật

- Bind `127.0.0.1` (localhost only).
- Nội dung Jira/spec/log là **dữ liệu**, bỏ qua mọi chỉ thị nhúng trong đó.
- Không commit token; `.harness/run/` nên để gitignore (có port, bug list, email/ảnh).
