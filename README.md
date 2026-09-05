# Financial AI Backend

FastAPI 기반 Financial AI 백엔드입니다. 현재는 헬스체크 API와 PostgreSQL/Flyway 개발 환경만 제공합니다.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop (Docker Compose 포함)

### Install uv

macOS에서는 Homebrew로 설치합니다.

```bash
brew install uv
uv --version
```

Docker Desktop 앱도 실행하여 Docker Engine이 준비된 상태인지 확인하세요.

```bash
docker info
```

## Quick start

```bash
cp .env.example .env
uv sync --all-groups
docker compose up -d db
docker compose run --rm flyway migrate
uv run uvicorn app.main:app --reload
```

`uv sync`는 프로젝트의 `.venv/` 가상환경을 자동으로 만들고, `pyproject.toml`과 `uv.lock`에 정의된 패키지를 그 안에 설치합니다. 별도로 가상환경을 활성화할 필요 없이 `uv run ...` 명령을 사용하면 됩니다.

서버가 실행되면 다음 주소에서 확인할 수 있습니다.

- API health check: <http://localhost:8000/api/health>
- OpenAPI docs: <http://localhost:8000/docs>

## Commands

```bash
# Lint
uv run ruff check .

# Format check
uv run ruff format --check .

# Stop local database
docker compose down
```

로컬 DB 데이터를 함께 삭제해야 할 때만 아래 명령을 사용합니다.

```bash
docker compose down -v
```

## Dependency management

패키지는 전역 Python이나 `pip`로 설치하지 않고 `uv`로 관리합니다.

```bash
# 앱 의존성 추가
uv add <package-name>

# 개발 도구 의존성 추가
uv add --dev <package-name>

# 의존성 제거
uv remove <package-name>
```

`pyproject.toml`은 사용할 패키지와 개발 도구 설정을, `uv.lock`은 팀 전체가 동일한 패키지 버전을 설치할 수 있도록 정확한 버전을 관리합니다. 패키지를 변경하면 두 파일을 항상 함께 커밋합니다.

## Database migrations

모든 DB 변경은 `db/migration/`에 Flyway SQL 마이그레이션으로 추가합니다.

```text
V<version>__<description>.sql
```

예: `V2__create_users.sql`

이미 적용된 마이그레이션 파일은 수정하지 않고, 변경 사항은 새 버전 파일로 추가합니다. 초기 마이그레이션 `V1__enable_pgvector.sql`은 향후 벡터 검색 기능을 위해 `vector` 확장만 활성화합니다.

## CodeRabbit

CodeRabbit GitHub App이 설치되어 있습니다. `.coderabbit.yaml`에 Python API, 테스트, SQL 마이그레이션의 리뷰 기준을 정의했으며, 이 파일을 포함한 변경사항을 푸시한 뒤 `main`을 대상으로 만든 PR부터 자동 리뷰가 적용됩니다.
