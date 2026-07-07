#!/usr/bin/env python3
"""KRX 전 종목 티커→종목명 매핑 생성기 (OpenDART corpCode 재활용)."""
from __future__ import annotations
import json
from pathlib import Path
from tradingagents.dataflows.dart import get_api_key, _corp_code_map

def main() -> None:
    api_key = get_api_key()
    corp_map = _corp_code_map(api_key)
    names: dict[str, str] = {}
    for stock_code, info in corp_map.items():
        name = (info.get("corp_name") or "").strip()
        if not name or not stock_code.isdigit() or len(stock_code) != 6:
            continue
        names[stock_code] = name
    out = Path(__file__).resolve().parent.parent / "tradingagents" / "dataflows" / "data" / "krx_ticker_names.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"OK: {len(names)}종목 → {out}")
    for code in ("005930", "000660"):
        print(f"  {code}: {names.get(code)}")

if __name__ == "__main__":
    main()
