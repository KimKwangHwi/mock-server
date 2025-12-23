import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from generators import DYNAMIC_HANDLERS
# 전역 변수로 데이터 로드
MOCK_DB = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 JSON 파일 로드
    global MOCK_DB
    file_path = os.path.join(os.path.dirname(__file__), "mock_data.json")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            MOCK_DB = json.load(f)
        print(f"✅ Loaded {len(MOCK_DB)} endpoints from mock_data.json")
    except Exception as e:
        print(f"❌ Error loading mock_data.json: {e}")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("{full_path:path}")
async def handle_request(full_path: str, request: Request):
    """
    모든 GET 요청을 받아서 처리하는 핸들러
    """
    # 1. 엔드포인트 주소 파싱
    endpoint = "" + full_path
    
    # 2. 엔드포인트 존재 여부 확인
    if endpoint not in MOCK_DB:
        return JSONResponse(
            status_code=404,
            content="존재하지 않는 엔드포인트입니다" 
        )

    # 3. 파라미터 검증 로직
    spec = MOCK_DB[endpoint]
    required_params = set(spec.get("params", []))
    received_params = set(request.query_params.keys())

    # 파라미터 집합이 정확히 일치해야 함 (누락도 안되고, 쓸데없는 게 있어도 안됨)
    if required_params != received_params:
        return JSONResponse(
            status_code=400,
            content="잘못된 파라미터 접근입니다." # 
        )

    response_value = spec["value"] # 기본값은 JSON 값

    if endpoint in DYNAMIC_HANDLERS:
        # 동적 처리가 필요한 엔드포인트라면 함수 실행 결과를 사용
        # (필요하다면 request의 query param을 함수에 전달할 수도 있음)
        response_value = DYNAMIC_HANDLERS[endpoint]()
    
    # 4. 검증 통과 -> 값 반환
    return response_value