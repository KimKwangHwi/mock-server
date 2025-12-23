# TORUS Mock Server

이 프로젝트는 CNC 공작기계 데이터 수집을 위한 TORUS API를 모방하는 모의 서버입니다. FastAPI를 사용하여 웹 서버를 구축하고, 동적으로 생성되거나 정적인 JSON 형식의 데이터를 제공합니다.

## 프로젝트 구조

- `app/`: 핵심 애플리케이션 폴더
  - `main.py`: 모든 GET 요청을 처리하는 FastAPI 메인 파일
  - `generators.py`: 동적 데이터(예: 축 위치, 스핀들 속도, 가공 시간) 생성을 위한 함수 포함
  - `mock_data.json`: API 응답을 모방하기 위한 정적 데이터
- `database.py`: `motor`를 사용한 MongoDB 데이터베이스 연결 설정
- `Dockerfile`: 프로젝트의 Docker 이미지 빌드를 위한 지침
- `docker-compose.yml`: Docker Compose를 사용하여 `torus-mock` 서비스를 실행하기 위한 구성
- `requirements.txt`: 프로젝트에 필요한 Python 의존성 목록
- `.gitignore`: Git 버전 관리에서 불필요한 파일 및 폴더를 제외하기 위한 파일
- `temp.txt`: 설정의 일부를 포함하는 임시 파일

## 시작하기

### 사전 요구 사항

- Docker 설치

### 설치 및 실행

1.  **컨테이너 빌드 및 실행:**
    프로젝트의 루트 폴더에서 다음 명령어를 실행합니다:

    ```bash
    docker-compose up --build
    ```

2.  **동작 확인:**
    서버는 `http://localhost:8000` 주소에서 접근할 수 있습니다. 다양한 엔드포인트로 GET 요청을 보내 데이터를 수신할 수 있습니다.

## API 엔드포인트

서버는 `app/mock_data.json` 파일의 키와 경로가 일치하는 모든 GET 요청을 처리합니다.

### 요청 예시

```bash
curl http://localhost:8000/machine/list
```

### 동적 데이터

일부 엔드포인트는 동적으로 생성된 데이터를 반환합니다. 이러한 엔드포인트와 해당 생성 함수는 `app/generators.py` 파일의 `DYNAMIC_HANDLERS` 딕셔너리에 정의되어 있습니다.

**동적 데이터 엔드포인트 예시:**

- `/machine/channel/axis/machinePosition`: 현재 장비 축 위치
- `/machine/channel/spindle/rpm/actualSpeed`: 현재 스핀들 속도
- `/machine/currentCncTime`: ISO 형식의 현재 시간
- 등등

### 정적 데이터

엔드포인트에 매핑된 생성 함수가 없는 경우, 서버는 `app/mock_data.json` 파일에서 해당 값을 반환합니다.

## 데이터 생성

`app/generators.py` 모듈은 공작기계 작동을 모방하기 위해 현실적이면서도 무작위적인 데이터를 생성하는 역할을 합니다. 이 모듈의 함수들은 현재 시간과 난수를 사용하여 다음과 같은 다양한 지표를 생성합니다:

- 사인 곡선으로 변하는 축 위치
- 약간의 변동이 있는 부하 및 온도
- 증가하는 카운터 및 가공 시간
- 무작위 알람 상태
- 등등