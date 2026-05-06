# Telegram Claude Bot

> [简体中文](./README.md) · [繁體中文](./README.zh-TW.md) · [English](./README.en.md) · [日本語](./README.ja.md) · [한국어](./README.ko.md)

[Claude Code](https://claude.com/claude-code) CLI를 Telegram으로 감싸는 봇입니다. 스마트폰에서 채팅으로 명령을 보내기만 하면, 로컬 워크스테이션의 Claude가 장시간 작업을 실행하고 코드를 수정하며 commit까지 만들어 줍니다.

## 특징

- **다중 세션 병렬 실행**: 한 세션 = 한 프로젝트 디렉터리. 세션 간 작업은 서로를 블로킹하지 않습니다
- **백그라운드 실행 + 진행 상황 푸시**: 장시간 작업(기본 1시간 하드 리밋)은 백그라운드에서 실행되며, 처음 5분간은 4초마다, 이후 2분마다 진행 메시지를 갱신합니다. 완료 시 결과를 능동적으로 푸시합니다
- **프리뷰 모드**: `/preview`로 Claude에게 먼저 계획을 제시시키고 `/confirm`으로 실제 실행
- **작업 관리**: `/tasks`로 모든 병렬 작업 조회, `/kill`로 자식 프로세스 즉시 종료
- **화이트리스트 인증**: 지정된 Telegram User ID만 허용
- **경로 자동 보완**: `shulex/` 하위 디렉터리는 prefix 생략 가능 (프로젝트 특화, 변경 가능)
- **크래시 복구**: sessions.json에 영속화. 봇 재시작 시 stale running 플래그를 정리하고 사용자에게 알립니다

## 명령어

```
/help               전체 도움말 표시
/new <이름> <PJ>    새 세션 생성. 예: /new refactor shulex-gpt
/switch <이름>      세션 전환
/list               모든 세션 나열
/drop <이름>        세션 삭제 (실행 중인 세션은 삭제 불가)
/status             현재 세션 상태
/tasks              모든 작업 실행 상태
/kill [이름]        현재(또는 지정한) 세션의 작업 종료
/run <요청>         즉시 실행
/preview <요청>     프리뷰 모드: 계획부터 제시
/confirm            프리뷰한 작업 실행
/cancel             프리뷰 취소
/mode auto|preview  기본 모드 설정 (일반 텍스트는 이 모드를 따름)
```

일반 텍스트 메시지를 보내면 현재 모드에 따라 `/run` 또는 `/preview`가 트리거됩니다.

## 설치

### 1. 사전 요구 사항

- Python **3.10+**
- [Claude Code CLI](https://claude.com/claude-code) 설치 및 로그인 완료
- Windows의 경우 Git Bash (Claude CLI 의존성)

### 2. 의존성 설치

```bash
git clone <리포지토리 URL>
cd telegram-claude-bot
pip install -r requirements.txt
```

### 3. `.env` 설정

```bash
cp .env.example .env
```

`.env` 편집:

```ini
BOT_TOKEN=@BotFather에서 발급받은 token
ALLOWED_USER_ID=본인의 Telegram User ID (@userinfobot로 확인)
WORKSPACE_ROOT=E:/workspace
GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe   # Windows 필수
```

### 4. 실행

```bash
python bot.py
```

#### Windows 자동 시작 (선택)

관리자 권한으로 `setup_autostart.ps1`을 실행하면 작업 스케줄러에 등록되어 부팅 시 자동 실행됩니다. 또는 `start_bot.vbs`로 사일런트 실행할 수 있습니다.

## 프로젝트 구조

```
bot.py             진입점. 명령 핸들러 등록
handler.py         명령 비즈니스 로직
task_manager.py    백그라운드 작업 스케줄링 + 진행 스로틀링
claude_runner.py   claude CLI 비동기 스트리밍 래퍼 (stream-json 파싱)
session_store.py   sessions.json 영속화
path_resolver.py   프로젝트 경로 해석 (shulex 하위 디렉터리 캐시 포함)
git_helper.py      git diff 요약
text_utils.py      긴 메시지를 단락/줄 경계로 분할
config.py          .env 로더
```

## 동작 원리

1. Telegram이 명령을 수신 → `handler.py`가 화이트리스트 검증
2. 명령이 `task_manager.start()`로 디스패치되고, 백그라운드 asyncio 작업이 `claude_runner.run_async()`를 구동
3. `claude_runner`가 `--output-format stream-json`으로 `claude.cmd`를 실행하고, 이벤트 스트림(`tool_use` / `text` / `result`)을 파싱
4. `task_manager`가 `edit_message_text` 호출을 스로틀링하여 진행 메시지를 갱신
5. 완료 시 진행 메시지를 헤더로 다시 작성하고, 별도 메시지로 전체 응답 + `git diff` 요약을 전송

## 주의 사항

- 한 세션은 동시에 하나의 작업만 실행 가능. 병렬 실행이 필요하면 여러 세션 사용
- 하드 리밋 1시간 (`HARD_LIMIT_SEC`). 도달 시 자식 프로세스 강제 종료
- 동일 세션에서 연속으로 `/run`을 호출하면 Claude 컨텍스트가 자동으로 이어집니다 (`--resume <session_id>`)
- `bot.log`는 `.gitignore`에 포함되어 있습니다. commit 하지 마세요

## License

MIT
