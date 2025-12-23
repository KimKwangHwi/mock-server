# services/history_logger.py
from datetime import datetime
from datetime import timedelta
from database import get_db
from typing import Optional, Dict, Any, List
from pymongo import DESCENDING
from zoneinfo import ZoneInfo
import asyncio

class APIHistoryLogger:
    def __init__(self):
        self.db = None
        self.history_coll = None
        self.error_coll = None

    async def initialize(self):
        """초기화"""
        self.db = await get_db()
        self.history_coll = self.db.api_history
        self.error_coll = self.db.api_errors

        common_index = [("index.endpoint", 1), ("index.params.machine", 1)]

        # 일반 로그용 인덱스 (unique 조합)
        await self.history_coll.create_index(common_index)

        # 에러 로그용 인덱스 (unique 조합)
        await self.error_coll.create_index(common_index)

        print("✅ APIHistoryLogger 초기화 완료 (api_history, api_error 컬렉션 준비됨)")
        # 인덱스 생성 (성능 최적화)
        print("✅ API History Logger 초기화 완료")

    async def log_batch(
        self, endpoint_list: List[str], params_list: List[Dict], results: List[Any]
    ):
        """
        API 호출 결과 일괄 저장 (문서당 하나의 로그)
        에러 여부에 따라 서로 다른 컬렉션에 저장합니다.
        """
        if self.history_coll is None or self.error_coll is None:
            await self.initialize()

        history_logs_to_insert = []
        error_logs_to_insert = []

        # 1. 삽입할 로그들을 에러/정상으로 분류하여 리스트에 준비
        for endpoint, params, result in zip(endpoint_list, params_list, results):
            is_error = self._is_error(result)
            timestamp = datetime.now(ZoneInfo("Asia/Seoul"))

            if is_error:
                # 에러 로그 문서 구조
                error_log_doc = {
                    "endpoint": endpoint,
                    "params": params,
                    "error": {  # result 대신 error 필드로 명확화
                        "status": result.get("status"),
                    },
                    "timestamp": timestamp,
                }
                error_logs_to_insert.append(error_log_doc)
            else:
                # 정상 로그 문서 구조
                history_log_doc = {
                    "endpoint": endpoint,
                    "params": params,
                    "result": result,
                    "timestamp": timestamp,
                }
                history_logs_to_insert.append(history_log_doc)

        # 2. 준비된 리스트를 각 컬렉션에 한 번에 삽입 (Bulk Insert)
        try:
            if history_logs_to_insert:
                await self.history_coll.insert_many(history_logs_to_insert)

            if error_logs_to_insert:
                await self.error_coll.insert_many(error_logs_to_insert)

        except Exception as e:
            print(f"⚠️ 일괄 로그 저장 실패: {e}")

    def _is_error(self, result):
        """에러 여부 확인"""
        if isinstance(result, dict) and result.get("__error__"):
            return True
        return False

    async def find_logs(
        self, endpoint: str, params: dict, limit: int = 10, is_error: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        특정 endpoint+params 문서에서 최근 N개 로그 조회.
        반환:
            - 문서가 존재하면 해당 문서(필요 필드만 포함)
            - 문서가 없거나 오류가 발생하면 None을 반환
            - is_error=True → 에러 컬렉션에서 조회
            - is_error=False → 정상 로그 컬렉션에서 조회
        """
        if self.history_coll is None or self.error_coll is None:
            await self.initialize()

        coll = self.error_coll if is_error else self.history_coll
        field = "error" if is_error else "answer"

        try:
            # 문서가 없을 수 있으므로 find_one 결과가 None일 수 있음
            doc = await coll.find_one(
                {"index.endpoint": endpoint, "index.params": params},
                {field: {"$slice": -limit}, "index": 1, "last_updated": 1},
            )
            # doc이 None이면 호출자(서비스)에 None을 반환
            return doc
        except Exception as e:
            # DB 접근 오류 등 예외 발생 시 로그 출력 후 None 반환
            # 실제 서비스에서는 로거를 써서 에러를 남기는 것이 좋음
            print(f"⚠️ find_logs DB error for {endpoint} {params}: {e}")
            return None


    async  def find_logs_time(
        self,
        endpoint: str,
        params: dict,
        limit: int = 10,
        is_error: bool = False,
        start_time: datetime = None,  # 시작 시간 파라미터 추가
        end_time: datetime = None  # 종료 시간 파라미터 추가
    ):
        """
        특정 endpoint+params 조합의 로그를 시간순으로 조회합니다. (문서당 1로그 스키마 기준)
        - is_error=True → 에러 컬렉션에서 조회
        - is_error=False → 정상 로그 컬렉션에서 조회
        """
        try:
            if self.history_coll is None or self.error_coll is None:
                await self.initialize()

            coll = self.error_coll if is_error else self.history_coll

            # 1. 기본 필터 조건 (새 스키마에 맞게 수정)
            filter_query = {"endpoint": endpoint, "params": params}

            # 2. 시간 범위 조건 추가 (새 스키마에 맞게 수정)
            time_query = {}
            if start_time:
                time_query["$gte"] = start_time
            if end_time:
                time_query["$lte"] = end_time
    
            if time_query:
                # timestamp가 최상위 필드이므로 바로 추가
                filter_query["timestamp"] = time_query
                
            projection = {
                "endpoint": 0,
                "params": 0,
            } # 중복되어서 반환되는 필드들은 제외시킴
            
            # 3. Aggregation 대신 find 사용
            #    - filter_query로 문서를 찾고,
            #    - timestamp 기준 최신순(-1)으로 정렬한 뒤,
            #    - limit 개수만큼 가져옵니다.
            cursor = coll.find(filter_query, projection).sort("timestamp", -1).limit(limit)
    
            result_docs = await cursor.to_list(length=None)
        
            if not result_docs:
                print(f"조건에 맞는 로그를 찾을 수 없습니다: {filter_query}")
                return []  # None 대신 빈 리스트를 반환하는 것이 더 안전할 수 있습니다.
    
            # 4. 조회된 문서 리스트를 그대로 반환
            # 현재 endpoint, params가 겹쳐서 출력되는데 이 경우 projection을 사용해 필요한 필드만 선택할 수 있습니다.
            return result_docs
            
        
    
        except Exception as e:
            print(f"로그 조회 중 예상치 못한 오류가 발생했습니다: {e}")
            return {"error": "An unexpected error occurred."}

    async def get_top_error_codes(
        self,
        limit: int = 3,
        start_time: datetime = None, 
        end_time: datetime = None 
    ) -> List[Dict[str, Any]]:
        """
        [툴 1] 특정 기간 동안 가장 많이 발생한 에러 코드를 N개 조회합니다.
        (에러 컬렉션: self.error_coll 사용)
        """
        if self.error_coll is None:
            await self.initialize()

        # 1. 시간 필터링을 위한 $match 파이프라인 준비
        match_stage = {}
        time_query = {}
        if start_time:
            time_query["$gte"] = start_time
        if end_time:
            time_query["$lte"] = end_time
        
        if time_query:
            match_stage = {'$match': {'timestamp': time_query}}
        
        pipeline = [
            # $match가 비어있지 않은 경우에만 파이프라인에 추가
            {'$group': {'_id': '$error.status', 'count': {'$sum': 1}}},
            {'$sort': {'count': DESCENDING}},
            {'$limit': limit}
        ]
        
        if match_stage:
            pipeline.insert(0, match_stage) # 시간 필터가 있으면 맨 앞에 추가

        try:
            cursor = self.error_coll.aggregate(pipeline)
            return await cursor.to_list(length=None)
        except Exception as e:
            print(f"⚠️ get_top_error_codes 집계 실패: {e}")
            return []

    async def get_top_error_endpoints(
        self,
        limit: int = 1,
        start_time: datetime = None,  
        end_time: datetime = None 
    ) -> List[Dict[str, Any]]:
        """
        [툴 2] 특정 기간 동안 에러가 가장 많이 발생한 엔드포인트+파라미터 조합을 N개 조회합니다.
        (에러 컬렉션: self.error_coll 사용)
        """
        if self.error_coll is None:
            await self.initialize()

        match_stage = {}
        time_query = {}
        if start_time:
            time_query["$gte"] = start_time
        if end_time:
            time_query["$lte"] = end_time
        
        if time_query:
            match_stage = {'$match': {'timestamp': time_query}}

        pipeline = [
            {'$group': {'_id': {'endpoint': '$endpoint', 'params': '$params'}, 'count': {'$sum': 1}}},
            {'$sort': {'count': DESCENDING}},
            {'$limit': limit}
        ]
        
        if match_stage:
            pipeline.insert(0, match_stage)

        try:
            cursor = self.error_coll.aggregate(pipeline)
            return await cursor.to_list(length=None)
        except Exception as e:
            print(f"⚠️ get_top_error_endpoints 집계 실패: {e}")
            return []

    async def get_top_params_for_endpoint(
        self,
        endpoint: str,
        limit: int = 1,
        start_time: datetime = None, 
        end_time: datetime = None 
    ) -> List[Dict[str, Any]]:
        """
        [툴 3] 특정 엔드포인트에서 가장 자주 "사용된" 파라미터 조합을 N개 조회합니다.
        (정상 로그 컬렉션: self.history_coll 사용)
        """
        if self.history_coll is None:
            await self.initialize()

        # 1. 기본 필터: endpoint는 필수
        match_filter = {'endpoint': endpoint}

        # 2. 시간 필터 추가
        time_query = {}
        if start_time:
            time_query["$gte"] = start_time
        if end_time:
            time_query["$lte"] = end_time
        
        if time_query:
            match_filter['timestamp'] = time_query
            
        pipeline = [
            {'$match': match_filter},
            {'$group': {'_id': '$params', 'count': {'$sum': 1}}},
            {'$sort': {'count': DESCENDING}},
            {'$limit': limit}
        ]

        try:
            cursor = self.history_coll.aggregate(pipeline)
            return await cursor.to_list(length=None)
        except Exception as e:
            print(f"⚠️ get_top_params_for_endpoint 집계 실패: {e}")
            return []

    async def get_cache(
        self, 
        endpoint: str, 
        params: dict, 
        check_count: int = 10
    ) -> Optional[Any]:
        """
        [캐시 툴] 최근 N개의 로그를 확인하여 결과값이 모두 동일한지 검사합니다.
        
        N개의 로그가 존재하고, 그 'result' 값이 모두 동일할 경우 (값이 안정된 경우)
        해당 'result' 값을 반환합니다. 그렇지 않으면 None을 반환합니다.

        Args:
            endpoint (str): 확인할 엔드포인트
            params (dict): 확인할 파라미터
            check_count (int): 확인할 최근 로그 개수 (N). 
                               기본값은 10입니다.

        Returns:
            Optional[Any]: 캐시 히트 시 'result' 값, 미스 시 None
        """
        # 시간 제약도 걸 수 있지만 일단 생략 
        
        if self.history_coll is None:
            await self.initialize()


        # Aggregation Pipeline을 사용하여 DB에서 모든 계산을 처리합니다.
        pipeline = [
            # 1. 원하는 endpoint와 params로 문서를 필터링
            {'$match': {
                'endpoint': endpoint,
                'params': params
            }},
            # 2. 최신순으로 정렬
            {'$sort': {'timestamp': DESCENDING}},
            # 3. 검사할 N개만 선택
            {'$limit': check_count},
            # 4. "result" 필드를 기준으로 그룹화
            {'$group': {
                '_id': '$result',      # 동일한 'result' 값끼리 묶음
                'count': {'$sum': 1} # 묶인 그룹의 개수를 셈
            }}
        ]

        try:
            cursor = self.history_coll.aggregate(pipeline)
            # 집계 결과를 리스트로 변환
            grouped_results = await cursor.to_list(length=None)

            # --- 5. 캐시 히트/미스 판별 ---

            # 5-1. [Cache Miss] 그룹이 1개가 아니다?
            #      -> 최근 N개 로그 중에 'result' 값이 다른 것이 섞여있다는 의미
            if len(grouped_results) >= 2:
                return "결과값이 일정하지 않아 조회가 필요합니다"
            elif len(grouped_results) <= 0:
                return "조회된 로그가 없습니다"

            # 5-2. [Cache Miss] 그룹은 1개인데, 개수가 N개보다 적다?
            #      -> 검사할 만큼(N개)의 로그가 아직 쌓이지 않았다는 의미
            if grouped_results[0].get('count') < check_count:
                return f"검사할 로그가 충분하지 않습니다. 현재 {grouped_results[0].get('count')} 개"

            # 5-3. [Cache Hit] 그룹이 1개이고, 개수도 N개와 일치
            #      -> 최근 N개의 로그가 존재하며, 그 'result' 값이 모두 동일함
            
            # $group의 _id가 'result' 값이므로 _id를 반환
            return grouped_results[0].get('_id') 

        except Exception as e:
            print(f"⚠️ get_cache 집계 실패 ({endpoint}): {e}")
            return None # 오류 발생 시에도 Cache Miss로 처리    

    async def get_endpoint_stats(
        self,
        endpoint: str,
        start_time: datetime = None,
        end_time: datetime = None
    ) -> Dict[str, Any]:
        """
        [툴 1] 특정 엔드포인트의 총 성공/에러 횟수를 반환합니다.
        
        Args:
            endpoint (str): (필수) 조회할 엔드포인트
            start_time (datetime, optional): (선택) 조회 시작 시간
            end_time (datetime, optional): (선택) 조회 종료 시간
        
        Returns:
            Dict[str, Any]: 통계 결과 딕셔너리
        """
        if self.history_coll is None or self.error_coll is None:
            await self.initialize()

        # 1. 공통 필터 생성
        match_filter = {"endpoint": endpoint}
        time_query = {}
        if start_time:
            time_query["$gte"] = start_time
        if end_time:
            time_query["$lte"] = end_time
        
        if time_query:
            match_filter["timestamp"] = time_query

        # 2. count_documents 작업을 병렬로 실행
        try:
            # 성공 횟수와 에러 횟수 조회를 동시에 요청
            success_task = self.history_coll.count_documents(match_filter)
            error_task = self.error_coll.count_documents(match_filter)

            # 두 작업이 끝날 때까지 대기
            s_count, e_count = await asyncio.gather(success_task, error_task)

            # 3. 결과 반환
            return {
                "endpoint": endpoint,
                "total_success": s_count,
                "total_errors": e_count,
                "total_requests": s_count + e_count
            }
        
        except Exception as e:
            print(f"⚠️ get_endpoint_stats 집계 실패: {e}")
            return {
                "endpoint": endpoint,
                "total_success": -1,
                "total_errors": -1,
                "total_requests": -1,
                "error_message": str(e)
            }

    async def get_error_code_counts(
        self,
        endpoint: str,
        start_time: datetime = None,
        end_time: datetime = None
    ) -> Dict[str, Any]:
        """
        [툴 2] 특정 엔드포인트의 에러 코드별 에러 횟수를 반환합니다.
        (에러 컬렉션: self.error_coll 사용)
        
        Args:
            endpoint (str): (필수) 조회할 엔드포인트
            start_time (datetime, optional): (선택) 조회 시작 시간
            end_time (datetime, optional): (선택) 조회 종료 시간
        
        Returns:
            Dict[str, Any]: 집계 결과 딕셔너리
        """
        if self.error_coll is None:
            await self.initialize()

        # 1. 기본 필터: endpoint는 필수
        match_filter = {'endpoint': endpoint}

        # 2. 시간 필터 추가
        time_query = {}
        if start_time:
            time_query["$gte"] = start_time
        if end_time:
            time_query["$lte"] = end_time
        
        if time_query:
            match_filter['timestamp'] = time_query
            
        # 3. Aggregation Pipeline 정의 (에러 코드별 그룹핑)
        pipeline = [
            {'$match': match_filter},
            {'$group': {'_id': '$error.status', 'count': {'$sum': 1}}},
            {'$sort': {'count': DESCENDING}}
        ]

        try:
            cursor = self.error_coll.aggregate(pipeline)
            results = await cursor.to_list(length=None)
            
            return {
                "endpoint": endpoint,
                "error_details": results  # 예: [{'_id': 'E-401', 'count': 10}, ...]
            }

        except Exception as e:
            print(f"⚠️ get_error_code_counts 집계 실패: {e}")
            return {"endpoint": endpoint, "error_details": [], "error_message": str(e)}


    # async def delete_all_logs(self):
    #     """모든 로그 삭제 (테스트용)"""
    #     if self.history_coll is None or self.error_coll is None:
    #         await self.initialize()
    #     await self.history_coll.delete_many({})
    #     await self.error_coll.delete_many({})
    #     print("✅ 모든 API 로그 삭제 완료")

    # async def delete_some_logs(self, days: int):
    #     """특정 일수 이전 로그 삭제 (테스트용)"""
    #     if self.history_coll is None or self.error_coll is None:
    #         await self.initialize()
    #     cutoff_date = datetime.now() - timedelta(days=days)
    #     history_result = await self.history_coll.delete_many({"last_updated": {"$lt": cutoff_date}})
    #     error_result = await self.error_coll.delete_many({"last_updated": {"$lt": cutoff_date}})
    #     print(f"✅ {days}일 이전의 API 로그 삭제 완료: history({history_result.deleted_count}), errors({error_result.deleted_count})")


# 싱글톤
history_logger = APIHistoryLogger()
