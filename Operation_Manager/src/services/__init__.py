# from src.services.project import ProjectService
from src.services.machine import MachineService

from src.repositories import (
    MachineRepository,
    get_machine_repository
)
# from src.repositories import (
#     ProjectRepository, FileRepository, RedisRepository, MachineLogRepository, MachineRepository,
#     get_log_repository, get_file_repository, get_machine_repository, get_project_repository, get_redis_repository
# )



async def get_machine_service():
    """
    MachineService 의존성 주입 팩토리.
    각 Repository의 async 생성자를 호출하여 서비스 객체를 반환.
    """
    machine_repo: MachineRepository = await get_machine_repository()
    # file_repo: FileRepository = await get_file_repository()
    # log_repo: MachineLogRepository = await get_log_repository()
    # redis_repo: RedisRepository = await get_redis_repository()
    return MachineService(machine_repo)