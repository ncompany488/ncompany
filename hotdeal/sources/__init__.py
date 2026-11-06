"""수집기 레지스트리.

각 수집기 모듈 규칙 (hotdeal/sources/<key>.py):
    SOURCE = SourceInfo(key="...", name="...", homepage="...", region="kr"|"global", kind="community"|"official")
    def fetch(limit: int = 40) -> list[Deal]: ...
- 네트워크는 반드시 hotdeal.http.get 사용 (robots.txt·속도 제한 준수)
- 제목·링크·숫자 메타데이터만 수집, 본문·이미지 원본 복제 금지
- 실패하면 예외를 던져도 됨 (러너가 소스별로 격리)
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def load_all() -> list[ModuleType]:
    mods = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:  # 한 수집기의 코드 오류가 전체 실행을 막지 않도록
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as e:
            print(f"[sources] {info.name} 불러오기 실패: {type(e).__name__}: {e}")
            continue
        if hasattr(mod, "SOURCE") and hasattr(mod, "fetch") and getattr(mod, "ENABLED", True):
            mods.append(mod)
    return sorted(mods, key=lambda m: m.SOURCE.key)
