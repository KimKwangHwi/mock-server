import time
import math
import random
from datetime import datetime

# 서버 시작 시간 기억 (가공 시간 계산용)
START_TIME = time.time()
MOCK_PROGRAM_DATA = [
    {"seq": 100, "block": "N100 G00 X0. Y0.", "active": "O1234 (TEST)"},
    {"seq": 110, "block": "N110 G01 Z-10. F1000", "active": "O1234 (TEST)"},
    {"seq": 120, "block": "N120 X50. Y50.", "active": "O1234 (TEST)"},
    {"seq": 130, "block": "N130 X100.", "active": "O1234 (TEST)"},
    {"seq": 140, "block": "N140 Y100.", "active": "O1234 (TEST)"},
    {"seq": 150, "block": "N150 X0. Y0.", "active": "O1234 (TEST)"},
    {"seq": 160, "block": "N160 G00 Z100.", "active": "O1234 (TEST)"},
    {"seq": 170, "block": "N170 M05", "active": "O1234 (TEST)"},
    {"seq": 180, "block": "N180 M30", "active": "O1234 (TEST)"}
]


def get_time_based_position():
    """시간에 따라 -50 ~ +50 사이를 부드럽게 왕복하는 좌표값"""
    t = time.time()
    # 10초 주기로 왕복 (150을 기준으로 ±50)
    return round(150.0 + math.sin(t * 0.6) * 50, 3)

def get_work_position():
    """기계 좌표와 약간 다르게 움직이는 가공 좌표"""
    t = time.time()
    return round(45.0 + math.sin(t * 0.6 + 1.0) * 45, 3)

def get_fluctuating_load(base=25.0, variation=2.0):
    """기준 부하값에서 약간씩 떨리는 값"""
    return round(base + random.uniform(-variation, variation), 1)

def get_spindle_rpm(target=2000.0):
    """목표 회전수 근처에서 미세하게 변하는 실제 RPM"""
    # 1995 ~ 2005 사이 변동
    return round(target + random.uniform(-5.0, 5.0), 1)

def get_machining_time():
    """서버 실행 후 경과 시간을 초 단위로 반환"""
    return round(time.time() - START_TIME, 1)

def get_current_iso_time():
    """현재 시간을 ISO 8601 포맷으로 반환"""
    return datetime.now().isoformat()

def get_increasing_counter():
    """시간에 따라 계속 증가하는 카운터 (가공 수량 시뮬레이션)"""
    # 10초에 1개씩 증가한다고 가정
    elapsed = time.time() - START_TIME
    return 50 + int(elapsed / 10)

# =====================================================================

def get_current_program_step():
    """시간에 따라 프로그램 리스트를 순환하며 현재 단계의 데이터를 반환"""
    # 5초마다 다음 블록으로 넘어감
    idx = int((time.time() - START_TIME) / 5) % len(MOCK_PROGRAM_DATA)
    return MOCK_PROGRAM_DATA[idx]

# 각 필드별 래퍼 함수 (핸들러 매핑용)
def get_current_block():
    return get_current_program_step()["block"]

def get_sequence_number():
    return get_current_program_step()["seq"]

def get_active_part_program():
    step = get_current_program_step()
    # 예: "O1234 (TEST); N110 G01 Z-10. F1000;" 형태로 조합
    return f"{step['active']}; {step['block']};"

def get_power_consumption(base_power=1200.0):
    """부하에 비례하여 전력 소모량 계산 (노이즈 추가)"""
    # 부하가 변하면 전력도 같이 변하는 것처럼 연출
    noise = random.uniform(-50.0, 50.0)
    return round(base_power + noise, 1)

def get_plc_bit():
    """PLC 비트 신호 (센서 On/Off 시뮬레이션)"""
    # 20% 확률로 True, 80% 확률로 False (간헐적 신호)
    return random.random() < 0.2

def get_plc_word():
    """PLC 워드 데이터 (16비트 정수, 상태 코드 등)"""
    # 0 ~ 100 사이의 임의의 상태 값
    return random.randint(0, 100)

def get_plc_dword():
    """PLC 더블워드 데이터 (32비트 정수, 카운터 등)"""
    return random.randint(1000, 50000)

def get_buffer_stream_value():
    """고속 샘플링 데이터 (진동 센서 값 시뮬레이션)"""
    # 0.0 ~ 1.0 사이의 값 (노이즈가 섞인 신호)
    return round(random.random(), 4)


def get_decreasing_tool_life(max_life=1000.0):
    """시간이 지날수록 줄어드는 공구 수명 (예지보전 테스트용)"""
    elapsed = time.time() - START_TIME
    # 1초에 0.5씩 수명이 깎인다고 가정
    rest_life = max_life - (elapsed * 0.5)
    # 0보다 작아지면 다시 새 공구(1000)로 교체된 척 리셋
    if rest_life < 0:
        rest_life = max_life - (rest_life % max_life)
    return round(rest_life, 1)

def get_increasing_tool_count():
    """시간이 지날수록 늘어나는 공구 사용 횟수"""
    elapsed = time.time() - START_TIME
    # 10초에 1회 가공 완료 가정
    return 100 + int(elapsed / 10)

def get_memory_capacity():
    """조금씩 변동하는 메모리 용량"""
    total = 2097152.0
    # 기본 사용량 51200에서 ±1000 정도 변동
    used = 51200.0 + random.uniform(-1000, 5000)
    free = total - used
    return (round(used, 0), round(free, 0))

# 메모리 사용량/남은용량은 서로 짝이 맞아야 하므로 별도 처리용
def get_used_capacity():
    return get_memory_capacity()[0]

def get_free_capacity():
    return get_memory_capacity()[1]

def get_random_alarm_status():
    """가끔씩 알람이 발생하는 상황 시뮬레이션"""
    # 5% 확률로 알람 발생, 95% 확률로 정상
    if random.random() < 0.05:
        return {"text": "SPINDLE OVERHEAT", "number": 2001}
    else:
        return {"text": "NO ALARM", "number": 0}

def get_alarm_text():
    return get_random_alarm_status()["text"]

def get_alarm_number():
    return get_random_alarm_status()["number"]

# ==========================================
# 1단계: 필수 모니터링 엔드포인트 매핑
# ==========================================
DYNAMIC_HANDLERS = {
    # 1. 축(Axis) 위치 및 부하
    "/machine/channel/axis/machinePosition": get_time_based_position,
    "/machine/channel/axis/workPosition": get_work_position,
    "/machine/channel/axis/axisLoad": lambda: get_fluctuating_load(25.0, 5.0),
    "/machine/channel/axis/axisFeed": lambda: get_fluctuating_load(1500.0, 10.0), # 이송속도 미세 변동
    
    # 2. 스핀들(Spindle)
    "/machine/channel/spindle/rpm/actualSpeed": lambda: get_spindle_rpm(2000.0),
    "/machine/channel/spindle/spindleLoad": lambda: get_fluctuating_load(40.0, 3.0),
    "/machine/channel/spindle/spindleTemperature": lambda: get_fluctuating_load(38.0, 0.5),

    # 3. 시간 및 카운터
    "/machine/currentCncTime": get_current_iso_time,
    "/machine/channel/workStatus/machiningTime/processingMachiningTime": get_machining_time,
    "/machine/channel/workStatus/workCounter/currentWorkCounter": get_increasing_counter,


    # [2단계: 프로그램 정보 및 전력 (NEW)]
    "/machine/channel/currentProgram/currentBlock": get_current_block,
    "/machine/channel/currentProgram/sequenceNumber": get_sequence_number,
    "/machine/channel/currentProgram/activePartProgram": get_active_part_program,
    
    # 전력 소비량 (축, 스핀들 각각)
    "/machine/channel/axis/axisPower/actualPowerConsumption": lambda: get_power_consumption(1200.0),
    "/machine/channel/spindle/spindlePower/actualPowerConsumption": lambda: get_power_consumption(5000.0),
    # [3단계: PLC 및 버퍼 (NEW)]
    "/machine/pic/memory/bitBlock": get_plc_bit,
    "/machine/pic/memory/rbitBlock": get_plc_bit,  # 읽기 전용 비트도 동일하게 처리
    "/machine/pic/memory/wordBlock": get_plc_word,
    "/machine/pic/memory/dwordBlock": get_plc_dword,
    "/machine/buffer/stream/value": get_buffer_stream_value,


    # [4단계: 공구 수명 (Health)]
    "/machine/channel/activeTool/toolEdge/toolLife/restToolLife": lambda: get_decreasing_tool_life(1000.0),
    "/machine/channel/activeTool/toolEdge/toolLife/toolLifeCount": get_increasing_tool_count,

    # [4단계: NC 메모리 (Resource)]
    "/machine/ncMemory/usedCapacity": get_used_capacity,
    "/machine/ncMemory/freeCapacity": get_free_capacity,

    # [4단계: 알람 상태 (Event)] - 주의: 에이전트가 당황할 수 있음!
    "/machine/channel/alarm/alarmText": get_alarm_text,
    "/machine/channel/alarm/alarmNumber": get_alarm_number, # JSON에서 값이 문자열인지 숫자인지 확인 필요 (여기선 문자열로 변환)

}