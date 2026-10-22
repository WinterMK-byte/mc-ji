# -*- coding: utf-8 -*-
"""sync_nutrition.py —— 从麦当劳 MCP 拉营养数据，刷新麦记手账

做什么：
    1. 调 list-nutrition-foods 拿餐品营养
    2. 调 query-my-coupons / available-coupons 拿手上的券（可选，失败不影响主流程）
    3. 归一化成统一结构
    4. 写回 mc_ji.html 里内嵌的 <script id="nutrition-data"> 块
       （内嵌而不是 fetch，是为了双击打开 file:// 也能用，不触发 CORS）
    5. 同时落一份 data/nutrition_snapshot.json 备查

用法：
    set MCD_MCP_TOKEN=xxx
    python tools/sync_nutrition.py              # 从 MCP 拉取并刷新
    python tools/sync_nutrition.py --offline    # 不联网，写入演示快照
    python tools/sync_nutrition.py --dry        # 只打印，不改文件

字段容错：
    麦当劳 MCP 的返回字段名可能调整，这里对常见别名做多路探测，
    并把原始返回同时写进 data/raw_*.json，方便日后核对。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.path.join(ROOT, "mc_ji.html")
DATA_DIR = os.path.join(ROOT, "data")

sys.path.insert(0, HERE)
from mcd_mcp import McpClient, McpError  # noqa: E402


# --------------------------------------------------------------------------
# 字段容错
# --------------------------------------------------------------------------
def pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    # 大小写无关再扫一遍
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low and low[k.lower()] not in (None, ""):
            return low[k.lower()]
    return default


def num(v, default=0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else default


def normalize_item(raw: dict, idx: int) -> dict | None:
    name = pick(raw, "name", "productName", "mealName", "title", "cnName", "餐品名称", "名称")
    if not name:
        return None
    return {
        "code": str(pick(raw, "code", "productCode", "sku", "id", "mealCode", default=f"item{idx}")),
        "name": str(name),
        "category": str(pick(raw, "category", "categoryName", "type", default="")),
        "energy_kcal": num(pick(raw, "energy", "energyKcal", "kcal", "calorie", "calories", "热量", "能量")),
        "protein_g": num(pick(raw, "protein", "proteinG", "蛋白质")),
        "fat_g": num(pick(raw, "fat", "fatG", "脂肪")),
        "carb_g": num(pick(raw, "carbohydrate", "carb", "carbG", "碳水", "碳水化合物")),
        "sodium_mg": num(pick(raw, "sodium", "sodiumMg", "钠")),
        "price_cny": num(pick(raw, "price", "priceCny", "salePrice", "价格")),
    }


def normalize_coupon(raw: dict) -> dict | None:
    name = pick(raw, "name", "couponName", "title", "券名称")
    if not name:
        return None
    expire = pick(raw, "expireDate", "endTime", "validEnd", "expire", "有效期")
    return {"name": str(name), "expire_text": str(expire) if expire else ""}


def extract_list(result) -> list[dict]:
    """MCP 返回可能是 content[].text 里的 JSON 串，也可能是 dict / list，全兼容。"""
    if result is None:
        return []
    if isinstance(result, list):
        return [x for x in result if isinstance(x, dict)]
    if isinstance(result, dict):
        for key in ("data", "items", "list", "foods", "meals", "products", "result"):
            v = result.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                for k2 in ("list", "items", "data"):
                    if isinstance(v.get(k2), list):
                        return [x for x in v[k2] if isinstance(x, dict)]
        if any(k in result for k in ("name", "productName", "mealName")):
            return [result]
    return []


def load_payload_text(client: McpClient, tool: str, args: dict) -> tuple[list[dict], str]:
    """调工具 → 拿到原始文本 → 解析成 list。返回 (结构化列表, 原始文本)。"""
    text = client.call_tool_text(tool, args)
    raw_text = text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 有时外面包了一层 markdown 代码块
        stripped = re.sub(r"^```[a-z]*\n|\n```$", "", text.strip())
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [], raw_text
    return extract_list(parsed), raw_text


# --------------------------------------------------------------------------
# 演示快照（无 token / 断网时保证界面可用）
# --------------------------------------------------------------------------
# 说明：以下是「结构演示用」的近似数值，用于演示交互，非官方实时结果。
#       真实数值请用 MCD_MCP_TOKEN 跑一次 sync_nutrition.py。
DEMO = {
    "source": "offline",
    "source_label": "离线演示快照",
    "items": [
        {"code": "big-mac", "name": "巨无霸", "category": "汉堡", "energy_kcal": 550, "protein_g": 25.0, "fat_g": 30.0, "carb_g": 42.0, "sodium_mg": 950, "price_cny": 25.0},
        {"code": "mcchicken", "name": "麦香鸡", "category": "汉堡", "energy_kcal": 400, "protein_g": 15.0, "fat_g": 21.0, "carb_g": 39.0, "sodium_mg": 700, "price_cny": 14.0},
        {"code": "spicy-chicken-burger", "name": "麦辣鸡腿堡", "category": "汉堡", "energy_kcal": 500, "protein_g": 22.0, "fat_g": 25.0, "carb_g": 45.0, "sodium_mg": 1000, "price_cny": 22.0},
        {"code": "fries-m", "name": "薯条（中）", "category": "小食", "energy_kcal": 340, "protein_g": 4.0, "fat_g": 16.0, "carb_g": 44.0, "sodium_mg": 250, "price_cny": 12.0},
        {"code": "nuggets-5", "name": "麦乐鸡（5 块）", "category": "小食", "energy_kcal": 230, "protein_g": 14.0, "fat_g": 13.0, "carb_g": 15.0, "sodium_mg": 460, "price_cny": 13.0},
        {"code": "coke-m", "name": "可口可乐（中）", "category": "饮料", "energy_kcal": 200, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 50.0, "sodium_mg": 15, "price_cny": 10.0},
        {"code": "sundae", "name": "朱古力圣代", "category": "甜品", "energy_kcal": 280, "protein_g": 6.0, "fat_g": 8.0, "carb_g": 45.0, "sodium_mg": 130, "price_cny": 9.0},
        {"code": "corn-cup", "name": "玉米杯", "category": "小食", "energy_kcal": 100, "protein_g": 3.0, "fat_g": 2.0, "carb_g": 19.0, "sodium_mg": 150, "price_cny": 10.0},
    ],
    "coupons": [
        {"name": "示例券：满 30 减 5", "expire_text": "演示数据"},
        {"name": "示例券：中薯买一送一", "expire_text": "演示数据"},
    ],
    "note": "离线演示快照：数值为近似演示值，非麦当劳官方实时结果。设置 MCD_MCP_TOKEN 后重新运行可获取真实数据。",
}


# --------------------------------------------------------------------------
# 写回 HTML
# --------------------------------------------------------------------------
BLOCK_RE = re.compile(
    r'(<script id="nutrition-data" type="application/json">)(.*?)(</script>)',
    re.S,
)


def inject(html: str, payload: dict) -> tuple[str, bool]:
    js = json.dumps(payload, ensure_ascii=False, indent=1)
    if not BLOCK_RE.search(html):
        return html, False
    new = BLOCK_RE.sub(lambda m: m.group(1) + "\n" + js + "\n" + m.group(3), html, count=1)
    return new, True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="刷新麦记手账的麦当劳营养数据")
    ap.add_argument("--offline", action="store_true", help="不联网，写入演示快照")
    ap.add_argument("--dry", action="store_true", help="只打印结果，不改文件")
    args = ap.parse_args(argv)

    os.makedirs(DATA_DIR, exist_ok=True)
    payload: dict

    if args.offline:
        payload = dict(DEMO)
        payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
        print("使用离线演示快照（--offline）")
    else:
        client = McpClient()
        try:
            info = client.initialize()
            print(f"已连接：{client.url}")
            print(f"  服务端：{json.dumps(info.get('serverInfo', {}), ensure_ascii=False)}")
        except McpError as e:
            print(f"[警告] 连接失败：{e}")
            print("       退回离线演示快照。设置 MCD_MCP_TOKEN 后重试可拿到真实数据。")
            payload = dict(DEMO)
            payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
            payload["mcp_error"] = str(e)
            args.offline = True

        if not args.offline:
            items_raw, raw1 = load_payload_text(client, "list-nutrition-foods", {})
            io.open(os.path.join(DATA_DIR, "raw_nutrition.json"), "w", encoding="utf-8").write(raw1)
            items = [x for x in (normalize_item(r, i) for i, r in enumerate(items_raw)) if x]
            print(f"营养餐品：{len(items)} 项")

            coupons: list[dict] = []
            for tool, cargs in (("query-my-coupons", {}), ("available-coupons", {})):
                try:
                    craw, raw2 = load_payload_text(client, tool, cargs)
                    if craw:
                        io.open(os.path.join(DATA_DIR, f"raw_{tool}.json"), "w", encoding="utf-8").write(raw2)
                    cs = [x for x in (normalize_coupon(r) for r in craw) if x]
                    if cs:
                        coupons = cs
                        print(f"优惠券（{tool}）：{len(cs)} 张")
                        break
                except McpError as e:
                    print(f"  跳过 {tool}：{e}")

            if not items:
                print("[警告] MCP 没返回可识别的餐品，改为演示快照（真实字段名可能已调整，见 data/raw_nutrition.json）")
                payload = dict(DEMO)
                payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
                payload["mcp_error"] = "MCP 返回中未识别到餐品字段"
            else:
                payload = {
                    "source": "mcp",
                    "source_label": "麦当劳 MCP 实时",
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "items": items,
                    "coupons": coupons,
                    "note": "数据由 list-nutrition-foods 等 MCP 工具实时拉取；价格与供应以官方渠道为准。",
                }

    # 落 json
    if not args.dry:
        io.open(os.path.join(DATA_DIR, "nutrition_snapshot.json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )

    # 写回 HTML
    html = io.open(HTML, encoding="utf-8").read()
    new_html, ok = inject(html, payload)
    if not ok:
        print("[错误] HTML 里找不到 <script id=\"nutrition-data\"> 块，未写入")
        return 1

    if args.dry:
        print("\n--- 将写入的数据（--dry 不落盘）---")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:1200])
        return 0

    io.open(HTML, "w", encoding="utf-8", newline="\n").write(new_html)
    print(f"已刷新 {os.path.relpath(HTML, ROOT)}：{len(payload.get('items', []))} 项餐品 / "
          f"{len(payload.get('coupons', []))} 张券  来源={payload['source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
