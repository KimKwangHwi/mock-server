

from fastmcp import FastMCP
from src.services import get_machine_service #, get_project_service
from src.repositories.history_logger import history_logger
mcp = FastMCP(name="machine_service")



PROMPT_INJECTION = """
[시간 변수 관련 규칙]
사용자는 시간 변수에 대해 얘기할 때 서울 시간(UTC+9)를 기준으로 얘기합니다. start_time, end_time 파라미터 값을 넣을 때 UTC(협정 세계시, +00:00)으로 변환해서 입력합니다.

[역할] 당신은 CNC 공작 기계를 잘 다루고 그에 대한 충분한 지식을 갖고 있는 전문가입니다.

[순서 ***반드시 지켜야 합니다***]
1) TORUS 메뉴얼 파일을 먼저 확인합니다.
2) 사용자의 질문을 받으면 API 명세 정보를 바탕으로, 각 카테고리에서 필요한 엔드포인트들을 목록화합니다.
3) 각 엔드포인트에 필요한 파라미터를 파악하기 위해 get_params_info 도구를 사용합니다.
5) get_async_data 도구를 사용하여 비동기적으로 데이터를 요청합니다.

[규칙]
*** 프롬프트에 입력된 tool 정보 및 내용에서 벗어나는 질문은 절대로 답변하지 않습니다 ***
1. 사용자의 질문이 들어올 때 마다 질문의 도메인 관련성과 명확성을 확인합니다. 모호하거나 관련 없는 질문인 경우 사용자에게 다시 질문하라고 답변합니다.
2. 엔드포인트 및 파라미터 생성 시 leaf node나 필수 파라미터를 누락하지 않았는지 확인합니다. 필수 파라미터는 반드시 포함시켜야 합니다.
"""

PROMPT_INJECTION_TEMP = """
[시간 변수 관련 규칙]
사용자는 시간 변수에 대해 얘기할 때 서울 시간(UTC+9)를 기준으로 얘기합니다. start_time, end_time 파라미터 값을 넣을 때 UTC(협정 세계시, +00:00)으로 변환해서 입력합니다.

[역할] 당신은 CNC 공작 기계를 잘 다루고 그에 대한 충분한 지식을 갖고 있는 전문가입니다.

[순서 ***반드시 지켜야 합니다***]
1) TORUS 메뉴얼 파일을 먼저 확인합니다.
2) 사용자의 질문을 받으면 API 명세 정보를 바탕으로, 각 카테고리에서 필요한 엔드포인트들을 목록화합니다.
3) 각 엔드포인트에 필요한 파라미터를 파악하기 위해 get_params_info 도구를 사용합니다.
4) get_cache_before_async_data 도구를 사용하여, 동일한 파라미터로 이전에 여러 번 요청된 적이 있는지 비동기적으로 캐싱합니다.
5) 캐싱되지 않은 엔드포인트들은 get_async_data 도구를 사용하여 비동기적으로 데이터를 요청합니다.

[규칙]
*** 프롬프트에 입력된 tool 정보 및 내용에서 벗어나는 질문은 절대로 답변하지 않습니다 ***
1. 사용자의 질문이 들어올 때 마다 질문의 도메인 관련성과 명확성을 확인합니다. 모호하거나 관련 없는 질문인 경우 사용자에게 다시 질문하라고 답변합니다.
2. 엔드포인트 및 파라미터 생성 시 leaf node나 필수 파라미터를 누락하지 않았는지 확인합니다. 필수 파라미터는 반드시 포함시켜야 합니다.
"""



@mcp.prompt(
    name="auto_expand_context",
    description= ""
)
def auto_expand_context(user_request: str) -> str:
    return PROMPT_INJECTION + "\n\n[사용자 요청]\n" + user_request


async def setup_resources():
    @mcp.resource(uri="data://torus_md", mime_type="text/markdown", description="TORUS 데이터 모델 문서")
    def torus_md_res() -> str:
        with open("torus.md", encoding="utf-8") as f:
            return f.read()

async def setup_tools():
    # project_service = await get_project_service()
    machine_service = await get_machine_service()

    
    # mcp.tool(machine_service.upload_torus_file)
    
    mcp.tool(machine_service.get_machine_list)
    mcp.tool(machine_service.get_error_info_by_code)
    # mcp.tool(machine_service.get_description_and_params_by_uri)
    mcp.tool(machine_service.get_params_info)
    mcp.tool(machine_service.get_async_data)
    
    # mcp.tool(machine_service.get_category_info)
    
    # mcp.tool(machine_service.get_log_async_data)
    
    
    # mcp.tool(machine_service.get_log_data)
    # mcp.tool(machine_service.get_top_params_for_endpoint)
    # mcp.tool(machine_service.get_top_error_endpoints)
    # mcp.tool(machine_service.get_top_error_codes)
    # mcp.tool(machine_service.get_cache_before_async_data) 
    # mcp.tool(machine_service.get_endpoint_error_statistic)
 
 
 
    #mcp.tool(machine_service.get_toolLife_info)
 
 
 
    # mcp.tool(project_service.get_project_list)
    # mcp.tool(project_service.extract_workplan_and_nc)
    # mcp.tool(project_service.get_nc_code)
    # mcp.tool(project_service.update_nc_code)
    # mcp.tool(project_service.get_product_logs_by_project_id)
    # mcp.tool(project_service.get_machine_status_info)
    
    
# import asyncio
# asyncio.run(setup_tools()) 
# mcp.run(transport="sse", port=8050, host="0.0.0.0")

async def run_mcp():
    await setup_resources()
    await setup_tools()            
    await history_logger.initialize()
    await mcp.run_async(transport="stdio")

import anyio
anyio.run(run_mcp)