import os
from src.repositories.machine import MachineRepository

# --- Torus Gateway API 연동 리포지토리 반환 ---
async def get_machine_repository() -> MachineRepository:
    """
    Torus Gateway 외부 API와 연동하는 머신 리포지토리 반환.
    환경 변수 TORUS_GATEWAY_URL 사용
    """
    torus_url = os.getenv("TORUS_GATEWAY_URL", "http://localhost:8000")
    return MachineRepository(torus_url)