import asyncio
from datetime import datetime
import re
from typing import Dict
from typing import List
from typing import Any, Tuple
import os
import yaml
from pathlib import Path
import uuid
import json
import logging
from src.repositories import MachineRepository
from src.schemas.machine import (
    MachineFileUploadResponse, MachineListResponse, MachineProgramStatusResponse, MachineInfo
)
from src.utils.exceptions import CustomException, ExceptionEnum
import logging

from src.repositories.history_logger import history_logger


def load_json_file(file_path: Path) -> Dict:
    """JSON 파일을 로드하는 유틸리티 함수"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.critical(f"치명적 오류: 필수 설정 파일({file_path})을 찾을 수 없습니다.")
        raise # 예외를 다시 발생시켜 프로그램 중단
    except json.JSONDecodeError:
        logging.critical(f"치명적 오류: 설정 파일({file_path})의 JSON 형식이 잘못되었습니다.")
        raise # 예외를 다시 발생시켜 프로그램 중단


def load_yaml_file(file_path: Path) -> Dict[str, Any]:
    """YAML 파일을 로드하는 유틸리티 함수"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.critical(f"치명적 오류: 필수 설정 파일({file_path})을 찾을 수 없습니다.")
        raise  # 예외를 다시 발생시켜 프로그램 중단
    except yaml.YAMLError as e:
        logging.critical(f"치명적 오류: 설정 파일({file_path})의 YAML 형식이 잘못되었습니다. 상세: {e}")
        raise  # 예외를 다시 발생시켜 프로그램 중단

class MachineService:
    """
    CNC 장비와 연동되는 주요 비즈니스 로직(목록 조회, 파일 전송, 상태 추적 등)을 담당하는 서비스 계층.
    """
    
    PARAMS_JSON = load_json_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'torus_manual/uri_params.json'))
    ERRORS_JSON = load_json_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'torus_manual/error_status.json'))
    #CATEGORY_JSON = load_json_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'torus_manual/api_category_uri.json'))
    CATEGORY_YAML = load_yaml_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'torus_manual/api_category.yaml'))
    

    
    def __init__(
        self, 
        machine_repo: MachineRepository
        # file_repo: FileRepository, 
        # log_repo: MachineLogRepository, 
        # job_tracker: RedisRepository
    ):
        """
        :param machine_repo: 장비 관련 외부 API 통신 리포지토리
        :param file_repo: 파일(GridFS) 관리 리포지토리
        :param log_repo: MongoDB 가공 로그 관리 리포지토리
        :param job_tracker: Redis 기반 상태 추적기
        """
        self.machine_repo = machine_repo
        # self.file_repo = file_repo
        # self.log_repo = log_repo
        # self.job_tracker = job_tracker
        

    async def upload_torus_file(self, project_id: str, machine_id: int, file_id: str) -> MachineFileUploadResponse:
        """
        NC 파일을 장비로 업로드 (중복 파일 삭제, 폴더 생성, 포맷 검증 등 포함).
        :param project_id: 프로젝트 ID
        :param machine_id: 장비 ID
        :param file_id: 업로드할 NC 파일의 GridFS ID
        :return: 업로드 결과 정보
        """
        # 1. 파일 내용 로드 및 파일명 추출
        byte_io, filename = await self.file_repo.get_file_byteio_and_name(file_id)
        file_data = byte_io.read()
        # 2. NC 루트 경로 및 작업 폴더 경로 확보
        ncpath_root = await self.machine_repo.get_nc_root_path(machine_id)
        project_folder_path = f"{ncpath_root}OM/"
        await self.machine_repo.ensure_folder_exists(machine_id, project_folder_path)
        
        project_folder_path = project_folder_path + f"{project_id}/"

        # 3. 해당 장비 정보 확인
        machines: MachineListResponse = await self.get_machine_list()
        matched_machine = next((m for m in machines.machines if m.id == machine_id), None)
        if not matched_machine:
            raise CustomException(ExceptionEnum.MACHINE_NOT_FOUND)

        # 4. FANUC 계열인 경우 NC 파일명 포맷 검증
        if matched_machine.vendorCode.lower() == "fanuc":
            content_str = file_data.decode(errors="ignore")
            o_match = re.search(r"\bO(\d+)", content_str)
            if not o_match:
                raise CustomException(ExceptionEnum.INVALID_SIMENSE_FORMAT)
            o_number = f"O{o_match.group(1)}"
            if not filename.startswith(o_number):
                raise CustomException(ExceptionEnum.INVALID_FILE_NAME_FORMAT)

        # 5. 폴더 생성 및 동일 파일 삭제, 파일 업로드
        await self.machine_repo.ensure_folder_exists(machine_id, project_folder_path)
        await self.machine_repo.remove_file_if_exists(machine_id, project_folder_path, filename)
        await self.machine_repo.put_nc_file(machine_id, project_folder_path, filename, file_data)
        self.job_tracker.set_status(project_id, filename, machine_id, "가공 대기")

        return MachineFileUploadResponse(
            status=0,
            filename=filename,
            machine_id=machine_id,
            ncpath=project_folder_path
        )


    async def track_all_machines_forever(self):
        """
        모든 CNC 장비의 가공 상태를 백그라운드에서 지속적으로 추적.
        신규 장비가 추가되면 자동으로 트래킹을 시작.
        """
        tracked_machines = set()
        while True:
            machines = await self.get_machine_list()
            machine_ids = [m.id for m in machines.machines]
            logging.info(f"📡 Found {len(machine_ids)} machines: {machine_ids}")

            for machine_id in machine_ids:
                if machine_id not in tracked_machines:
                    tracked_machines.add(machine_id)
                    logging.info(f"🛰️ Starting tracking for machine {machine_id}")
                    asyncio.create_task(self._track_single_machine(machine_id))
            await asyncio.sleep(10)

    async def _track_single_machine(self, machine_id: int):
        """
        단일 CNC 장비의 가공 상태를 실시간 모니터링, 공구 교체, 로그 적재 및 상태 변경 처리.
        (내부에서만 사용)
        """
        current_tool = None
        operation_index = 1
        product_uuid = str(uuid.uuid4())
        log_doc = None
        is_processing = False
        current_project_id = None
        current_filename = None

        while True:
            try:
                status = await self.get_machine_status(machine_id)
                logging.info(f"🔍 Machine {machine_id} status = {status.programMode}")

                if status.programMode == 3:  # 가공 중
                    program_path = await self.machine_repo.get_current_program_name(machine_id)
                    dir_path = os.path.dirname(program_path) 
                    program_name = os.path.basename(program_path)
                    project_id = self.job_tracker.find_project_id_by_filename(program_name, machine_id)

                    if dir_path == "//CNC_MEM/USER/LIBRARY":
                        continue

                    if not project_id:
                        logging.warning(f"⚠️ No project found for {program_name} on machine {machine_id}")
                        await asyncio.sleep(3)
                        continue

                    self.job_tracker.mark_processing(project_id, program_name, machine_id)
                    tool = await self.machine_repo.get_active_tool_number(machine_id)

                    if not is_processing:
                        # 가공 시작 시 로그 초기화
                        is_processing = True
                        current_tool = tool
                        current_project_id = project_id
                        current_filename = program_name
                        log_doc = {
                            "project_id": project_id,
                            "machine_id": machine_id,
                            "product_uuid": product_uuid,
                            "start_time": datetime.now(),
                            "finish_time": None,
                            "finished": False,
                            "operations": []
                        }
                        await self._log_product_operation(log_doc, operation_index, current_tool, "start")
                    elif tool != current_tool:
                        # 공구 변경 감지 시 이전 공구 종료 + 새 공구 시작
                        await self._log_product_operation(log_doc, operation_index, current_tool, "end")
                        operation_index += 1
                        await self._log_product_operation(log_doc, operation_index, tool, "start")
                        current_tool = tool

                elif is_processing:
                    # 가공 종료 시 상태 및 로그 정리
                    self.job_tracker.mark_finished(current_project_id, current_filename, machine_id)
                    logging.info(f"🏁 Finished: {current_filename} on machine {machine_id}")
                    await self._log_product_operation(log_doc, operation_index, current_tool, "end")
                    log_doc["finish_time"] = datetime.now()
                    log_doc["finished"] = True
                    await self.log_repo.insert_log(log_doc)
                    # 상태 초기화
                    product_uuid = str(uuid.uuid4())
                    is_processing = False
                    log_doc = None
                    current_project_id = None
                    current_filename = None

            except Exception as e:
                logging.error(f"❌ Error tracking machine {machine_id}: {e}", exc_info=True)
            await asyncio.sleep(3)

    async def _log_product_operation(self, log_doc: dict, index: int, tool_number: int, action: str):
        """
        가공/공구 로그를 기록 (operation 배열에 추가/수정).
        :param log_doc: 현재 가공 로그 dict
        :param index: operation index
        :param tool_number: 공구 번호
        :param action: 'start' or 'end'
        """
        if action == "start":
            operation = {
                "uuid": str(uuid.uuid4()),
                "index": index,
                "toolNumber": tool_number,
                "start_time": datetime.now(),
                "end_time": None
            }
            log_doc["operations"].append(operation)
        elif action == "end":
            for op in reversed(log_doc["operations"]):
                if op["index"] == index and op["end_time"] is None:
                    op["end_time"] = datetime.now()
                    break
 

    # ======================================================================
    
    async def get_machine_list(self) -> MachineListResponse:
        """
        현재 시스템에 등록된 모든 장비 정보를 반환.
        :return: MachineListResponse (장비 목록)
        """
        raw_list = await self.machine_repo.get_machine_list()
        machines = [MachineInfo(**item) for item in raw_list]
        return MachineListResponse(machines=machines)

    async def get_category_info(self, category: str):
        """
        TORUS API 카테고리 및 엔드포인트 정보를 반환합니다.
        Args:
            category (str): 조회할 카테고리 이름. 카테고리 이름은 반드시 다음 중 하나입니다 : 
                "장비 기본 정보"
                "채널 상태 정보"
                "축 상태 및 제어"
                "스핀들 상태 및 제어"         
                "이송 속도 및 오버라이드"
                "가공 상태 및 집계"
                "활성화된 공구 정보"
                "NC 프로그램 실행 정보"
                "좌표계 및 오프셋"
                "알람 및 에러"
                "사용자 변수"
                "CNC 내부 PLC 메모리 데이터"
                "장비 공구 영역 및 공구 정보"
                "센서 데이터 수집"
        Returns:
           '설명'이 포함된 딕셔너리.
        """
        category_info = self.CATEGORY_YAML.get(category)
        if category_info:
            return category_info
        else:
            return "카테고리 정보를 찾을 수 없습니다. 답변을 종료합니다."
        
    async def get_error_info_by_code(self, error_code: int) -> Dict[str, str]:
        """
        주어진 에러 코드(error_status)에 해당하는 분류와 설명을 반환합니다.

        Args:
            error_code (int): 조회할 9자리 에러 상태 코드.

        Returns:
            Dict[str, str]: '분류'와 '설명'이 포함된 딕셔너리.
                           에러 코드를 찾지 못하거나 파일이 없으면 에러 정보가 담긴 딕셔너리를 반환합니다.
        """
        # 입력된 정수형 에러 코드를 JSON 파일의 키 형식인 문자열로 변환합니다.
        error_code_str = str(error_code)
        
        error_info = self.ERRORS_JSON.get(error_code_str)
        
        if error_info:
            return error_info
        else:
            return {
                "분류": "Not Found",
                "설명": f"에러 코드 '{error_code}'에 해당하는 정보를 찾을 수 없습니다."
            }
            
    async def get_params_info(self, endpoint_list: List[str]):
        """
        - 사용자 질문에 들어오고 장비 목록(machine_list)가 반환된 후, 가장 먼저 호출되는 tool입니다. 
        - get_async_data tool을 호출하기 전에 반드시 호출되어야 합니다.
        - 여러 API 엔드포인트에 대한 필수 파라미터 정보를 한 번에 조회합니다.
        Args:
            endpoint_list: List[str] : API 엔드포인트.
            
        """
        results = {}
        
    
        for endpoint in endpoint_list:
            endpoint_info = self.PARAMS_JSON.get(endpoint)

            # 값이 존재할 경우에만 required_params를 찾습니다.
            if endpoint_info:
                params_info = endpoint_info.get("required_params")
            else:
                params_info = None  # 키가 없는 경우 None으로 처리
                
            results[endpoint] = params_info
                

        return results

        
    async def get_cache_before_async_data(self, endpoint_list: List[str], params_list: List[dict]):
        """
        - get_async_data 호출 전에, 동일한 endpoint+params 조합에 대해 최근 로그를 확인하여
          결과값이 변하지 않았는지 검사합니다.
        - 캐시 히트 시 이전 결과값을 반환하고, 미스 시 None을 반환합니다.
        
        Args:
            endpoint_list (List[str]): 조회할 API 엔드포인트 리스트.
            params_list (List[dict]): 각 엔드포인트에 대한 파라미터 딕셔너리 리스트. 
        """
        if len(endpoint_list) != len(params_list):
            return "엔드포인트 리스트와 파라미터 리스트의 길이는 같아야 합니다."
        
        asyncio_tasks = []
        for endpoint, params in zip(endpoint_list, params_list):
            asyncio_tasks.append(history_logger.get_cache(endpoint, params, check_count=5))
        
        results = await asyncio.gather(*asyncio_tasks)
        return results
        
    async def get_async_data(self, endpoint_list: List[str], params_list: List[dict]):
        """
        - 여러 API 엔드포인트에 대해 비동기적으로 데이터를 조회합니다.
        - endpoint_list와 params_list의 길이는 같아야 하며, 각 인덱스에 해당하는 엔드포인트와 파라미터로 요청이 이루어집니다.
        - 필요한 파라미터 값을 알고 있는 엔드포인트에 대해서만 호출해야 합니다.
        
        Args:
            endpoint_list (List[str]): 조회할 API 엔드포인트 리스트.
            params_list (List[dict]): 각 엔드포인트에 대한 파라미터 딕셔너리 리스트. 
        """
        
        if len(endpoint_list) != len(params_list):
            return "엔드포인트 리스트와 파라미터 리스트의 길이는 같아야 합니다."
        
        asyncio_tasks = []
        for endpoint, params in zip(endpoint_list, params_list):
            asyncio_tasks.append(self.machine_repo.get_data(endpoint, params))
        
        results = await asyncio.gather(*asyncio_tasks)

        asyncio.create_task(
            history_logger.log_batch(endpoint_list, params_list, results)
        )
        
        return results
    
    
    
    async def get_log_data(
        self,
        endpoint: str,
        params: dict,
        limit: int = 10,
        is_error: bool = False,
        start_time: datetime = None, 
        end_time: datetime = None   
    ) -> Dict[str, Any]:
        """
        단일 endpoint+params 쌍의 로그 데이터를 조회합니다.
        레포지토리 함수(history_logger.find_logs) 호출 및 결과 가공 포함.
        시간 정보 ex) 2025-11-04 09:18:02.503360+09:00
        """
        return await history_logger.find_logs_time(endpoint, params, limit, is_error, start_time, end_time)
    
    async def get_top_error_codes(
        self,
        limit: int = 3,
        start_time: datetime = None, 
        end_time: datetime = None 
    ) -> List[Dict[str, Any]]:
        """
        [툴 1] 특정 기간 동안 가장 많이 발생한 에러 코드를 N개 조회합니다.
        """
        return await history_logger.get_top_error_codes(limit, start_time, end_time)
    
    async def get_top_error_endpoints(
        self,
        limit: int = 1,
        start_time: datetime = None,  
        end_time: datetime = None 
    ) -> List[Dict[str, Any]]:
        """
        [툴 2] 특정 기간 동안 에러가 가장 많이 발생한 엔드포인트+파라미터 조합을 N개 조회합니다.
        시간 정보 ex) 2025-11-04 09:18:02.503360+09:00
        """
        return await history_logger.get_top_error_endpoints(limit, start_time, end_time)
    
    async def get_top_params_for_endpoint(
        self,
        endpoint: str,
        limit: int = 1,
        start_time: datetime = None, 
        end_time: datetime = None 
    ) -> List[Dict[str, Any]]:
        """
        [툴 3] 특정 엔드포인트에서 가장 자주 "사용된" 파라미터 조합을 N개 조회합니다.
        시간 정보 ex) 2025-11-04 09:18:02.503360+09:00
        """
        return await history_logger.get_top_params_for_endpoint(endpoint, limit, start_time, end_time)
    
    
    async def get_endpoint_error_statistic(
        self, 
        endpoint: str, 
        start_time: datetime = None, 
        end_time: datetime = None
        ) -> Dict[str, Any]:
        """
        [툴 4] 특정 엔드포인트에 대한 에러 통계 정보를 조회합니다.
        
        """
        try:
            task_stats = history_logger.get_endpoint_stats(
                endpoint, start_time, end_time
            )
            task_details = history_logger.get_error_code_counts(
                endpoint, start_time, end_time
            )

            # 2. asyncio.gather를 사용해 두 쿼리를 DB에 병렬로 실행
            stats_result, details_result = await asyncio.gather(
                task_stats, task_details
            )

            # 3. DB 쿼리 중 발생한 에러 처리
            if stats_result.get("error_message"):
                raise Exception(f"통계 조회 실패: {stats_result['error_message']}")
            if details_result.get("error_message"):
                raise Exception(f"에러 상세 조회 실패: {details_result['error_message']}")

            # 4. 두 결과를 조합하여 최종 리포트 생성
            total_requests = stats_result.get("total_requests", 0)
            total_errors = stats_result.get("total_errors", 0)
        
            # 에러율 계산
            error_rate = 0.0
            if total_requests > 0:
                error_rate = round((total_errors / total_requests) * 100, 2)
    
            # 5. 최종 리포트 반환
            return {
                "endpoint": endpoint,
                "total_requests": total_requests,
                "total_success": stats_result.get("total_success", 0),
                "total_errors": total_errors,
                "error_rate_percent": error_rate,
                "error_details": details_result.get("error_details", [])
            }

        except Exception as e:
            print(f"⚠️ get_endpoint_error_report 실행 중 오류: {e}")
            return {
                "endpoint": endpoint,
                "error": "리포트 생성에 실패했습니다.",
                "error_message": str(e)
            }
    
    
    
    
    async def get_toolLife_info(self, machine: int):
        """
        등록순 기준 공구 수명 정보를 비동기적으로 효율적이게 조회합니다. 장비 번호만 입력하면 됩니다.
        Args:
            machine (int): 조회할 장비 번호.
        """
        machine_param = {"machine": machine, "toolArea": 1}
        numberOfRegisteredTools = await self.machine_repo.get_data("/machine/toolArea/numberOfRegisteredTools", machine_param)

        # 1) 에러 응답이면 바로 리턴
        if isinstance(numberOfRegisteredTools, dict) and numberOfRegisteredTools.get("__error__"):
            return numberOfRegisteredTools

        # 2) 정상 값 정제
        # 리스트 형태인 경우 [17] → 17
        if isinstance(numberOfRegisteredTools, list):
            if numberOfRegisteredTools and isinstance(numberOfRegisteredTools[0], int):
                numberOfRegisteredTools = numberOfRegisteredTools[0]
            else:
                return "유효한 공구 개수를 확인할 수 없습니다."

        # 3) int가 아니면 잘못된 값
        if not isinstance(numberOfRegisteredTools, int):
            return "유효한 공구 개수를 확인할 수 없습니다."

        # 4) 정상 값인데 0 이하
        if numberOfRegisteredTools <= 0:
            return "등록된 공구가 없습니다."

        # 1. 모든 공구의 날(edge) 개수를 동시에 조회
        edge_tasks = []
        for i in range(1, numberOfRegisteredTools + 1):
            edge_params = machine_param.copy()
            edge_params["registerTools"] = i
            edge_tasks.append(
                self.machine_repo.get_data("/machine/toolArea/registerTools/numberOfEdges", edge_params)
            )
        numberOftoolEdgesList = await asyncio.gather(*edge_tasks)
        cleaned_edges_list = [n if isinstance(n, int) else 1 for n in numberOftoolEdgesList]
        # 2. 모든 공구의 모든 날에 대한 수명 정보 요청 태스크 생성
        life_info_tasks = []
        for i, num_edges in enumerate(cleaned_edges_list):
            tool_num = i + 1
            
            for j in range(1, num_edges + 1):
                base_params = {**machine_param, "registerTools": tool_num, "toolEdge": j}
                
                # 4가지 수명 정보 요청을 태스크 리스트에 추가
                life_info_tasks.append(self.machine_repo.get_data("/machine/toolArea/registerTools/toolEdge/toolLife/restToolLife", {**base_params, "restToolLife": 1}))
                life_info_tasks.append(self.machine_repo.get_data("/machine/toolArea/registerTools/toolEdge/toolLife/maxToolLife", {**base_params, "maxToolLife": 1}))
                life_info_tasks.append(self.machine_repo.get_data("/machine/toolArea/registerTools/toolEdge/toolLife/toolLifeCount", {**base_params, "toolLifeCount": 1}))
                base_params = {**{k: v for k, v in base_params.items() if k != "toolEdge"}, "toolLifeUnit": 1}
                life_info_tasks.append(self.machine_repo.get_data("/machine/toolArea/registerTools/toolLifeUnit", base_params))
                #life_info_tasks.append(self.machine_repo.get_data("/machine/toolArea/registerTools/toolEdge/toolLife/toolLifeAlarm", base_params))

        if not life_info_tasks:
            return "등록된 공구의 날 정보가 없습니다."

        # 3. 생성된 모든 수명 정보 태스크를 한 번에 실행
        all_results = await asyncio.gather(*life_info_tasks)

        # 4. 결과를 올바른 구조로 조합
        toolLife_info = []
        task_idx = 0  # 'results' 리스트를 순회하기 위한 인덱스 카운터
    
        for i, num_edges in enumerate(cleaned_edges_list):
            tool_num = i + 1
             # 날 개수가 유효한 정수일 때만 처리
            
            for j in range(1, num_edges + 1):
                # 4개의 결과가 한 세트
                result_chunk = all_results[task_idx : task_idx + 4]

                # API 에러 처리: 4개 중 하나라도 에러면 'error'로 표기, 아니면 값 할당
                rest_life = result_chunk[0] if not (isinstance(result_chunk[0], dict) and result_chunk[0].get("__error__")) else "error"
                max_life = result_chunk[1] if not (isinstance(result_chunk[1], dict) and result_chunk[1].get("__error__")) else "error"
                life_count = result_chunk[2] if not (isinstance(result_chunk[2], dict) and result_chunk[2].get("__error__")) else "error"
                #life_alarm = result_chunk[3] if not (isinstance(result_chunk[3], dict) and result_chunk[3].get("__error__")) else "error"
                life_unit = result_chunk[3] if not (isinstance(result_chunk[3], dict) and result_chunk[3].get("__error__")) else "error"
                toolLife_info.append({
                    "registerTools": tool_num,
                    "toolEdges": j,
                    "restToolLife": rest_life,
                    "maxToolLife": max_life,
                    "toolLifeCount": life_count,
                    "toolLifeUnit": life_unit
                    #"toolLifeAlarm": life_alarm
                })
                task_idx += 4 # 다음 결과 세트를 위해 인덱스를 4 증가

        return toolLife_info
    # =============================================================================================================
    
    
    
    
    
    #from typing import List, Dict, Any, Tuple
    async def get_log_async_data(
        self,
        endpoint_list: List[str],
        params_list: List[dict],
        limit: int = 10,
        is_error: bool = False,
        start_time: datetime = None, # 시작 시간 파라미터 추가
        end_time: datetime = None    # 종료 시간 파라미터 추가
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        - 특정 엔드포인트, 파라미터에 대한 최근 로그 데이터(이전 답변이 저장된 데이터)를 조회합니다.
        - endpoint_list와 params_list의 길이는 같아야 하며, 각 인덱스에 해당하는 엔드포인트와 파라미터로 로그 데이터 검색이 이루어집니다.
        - 정상 답변 데이터를 조회하는 경우 is_error는 False로, 에러 답변 데이터를 조회하는 경우 is_error는 True로 설정해야 합니다.

        Args:
            endpoint_list (List[str]): 조회할 API 엔드포인트 리스트.
            params_list (List[dict]): 각 엔드포인트에 대한 파라미터 딕셔너리 리스트. 
            limit (int): 각 엔드포인트+파라미터 조합에 대해 조회할 최대 로그 개수. 기본값은 10.
            is_error (bool): 에러 로그를 조회할지 여부. 기본값은 False
            start_time (datetime, optional): 조회 시작 시간. 기본값은 None.
            end_time (datetime, optional): 조회 종료 시간. 기본값은 None.

        Returns:
            Tuple[
                List[Dict[str, Any]],  # results: 각 조합의 로그 조회 결과 리스트
                List[Dict[str, Any]]   # errors: 조회 중 오류가 발생한 항목 리스트
            ]
        """
        if len(endpoint_list) != len(params_list):
            raise ValueError("endpoint_list and params_list must have the same length.")

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        asyncio_tasks = []

        # ✅ 1. 각 endpoint+params 조합별 조회 task 생성
        for endpoint, params in zip(endpoint_list, params_list):
            task = asyncio.create_task(
                self._fetch_single_log(endpoint, params, limit, is_error, start_time, end_time)
                
            )
            asyncio_tasks.append(task)

        # ✅ 2. 모든 task 병렬 실행
        task_results = await asyncio.gather(*asyncio_tasks, return_exceptions=True)

        # ✅ 3. 결과 처리 (예외 vs 정상 결과 구분)
        for endpoint, params, res in zip(endpoint_list, params_list, task_results):
            if isinstance(res, Exception):
                errors.append({
                    "endpoint": endpoint,
                    "params": params,
                    "error": str(res)
                })
            else:
                results.append(res)

        return results, errors
    
    async def _fetch_single_log(
        self,
        endpoint: str,
        params: dict,
        limit: int,
        is_error: bool,
        start_time: datetime, 
        end_time: datetime   
    ) -> Dict[str, Any]:
        """
        단일 endpoint+params 쌍의 로그 데이터를 조회하는 내부 헬퍼.
        레포지토리 함수(history_logger.find_logs) 호출 및 결과 가공 포함.
        """
        doc = await history_logger.find_logs_time(endpoint, params, limit=limit, is_error=is_error, start_time=start_time, end_time=end_time)
        if doc is None:
            return {
                "endpoint": endpoint,
                "params": params,
                "logs": "doc is None",
                "last_updated": None
            }

        field = "error" if is_error else "answer"
        logs = doc.get(field) or []
        last_updated = doc.get("last_updated")

        return {
            "endpoint": endpoint,
            "params": params,
            "logs": logs,
            "last_updated": last_updated
        }
        

    # async def get_description_and_params_by_uri(self, endpoint: str):
    #     """
    #     주어진 API 엔드포인트에 대한 설명과 필수 파라미터를 반환합니다.

    #     직전 tool 호출의 결과로 error_status : 538992680가 반환된 경우,
    #     이 tool을 호출하여 해당 엔드포인트의 설명과 필수 파라미터를 확인한 후,
    #     직전에 호출한 tool에 재입력하여 다시 시도할 수 있습니다.

    #     Args:
    #         endpoint (str): API 엔드포인트.

    #     Returns:
    #         dict: 엔드포인트에 대한 설명 및 필수 파라미터를 포함하는 딕셔너리.
    #             오류가 발생하면 "__error__" 키를 포함한 딕셔너리를 반환합니다.
    #     """
    #     current_dir = os.path.dirname(os.path.abspath(__file__))
    #     json_file_path = os.path.join(current_dir, '..', 'torus_manual/uri_params.json')
        
    #     api_info = self.PARAMS_JSON.get(endpoint)

    #     try:
    #         # JSON 파일을 비동기적으로 읽기
    #         async with aiofiles.open(json_file_path, 'r', encoding='utf-8') as f:
    #             file_content = await f.read()

    #         api_data = json.loads(file_content)

    #         # 엔드포인트 정보 검색
    #         api_info = api_data.get(endpoint)

    #         # 결과 반환
    #         if api_info:
    #             return {
    #                 "description": api_info.get("description"),
    #                 "required_params": api_info.get("required_params")
    #             }
    #         else:
    #             # 정보를 찾지 못한 경우
    #             return {
    #                 "__error__": True,
    #                 "message": f"엔드포인트 '{endpoint}'에 대한 정보를 찾을 수 없습니다.",
    #                 "endpoint": endpoint,
    #                 "full_api_response": None
    #             }

    #     except FileNotFoundError:
    #         return {
    #             "__error__": True,
    #             "message": "URI 및 파라미터 JSON 파일을 찾을 수 없습니다. 경로를 확인하세요."
    #         }
    #     except json.JSONDecodeError:
    #         return {
    #             "__error__": True,
    #             "message": "URI 및 파라미터 JSON 파일의 형식이 잘못되었습니다."
    #         }
    #     except Exception as e:
    #         return {
    #         "__error__": True,
    #         "message": f"알 수 없는 오류가 발생했습니다: {str(e)}"
    #         }