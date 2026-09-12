# -*- coding: utf-8 -*-
"""本地伴随服务 —— 给可视化面板解锁「抓取 / 工作流 / 文案生成 / 写库」能力。

为什么需要它：浏览器同源策略（CORS）决定了网页 JS 不能直接抓取电商平台页面，
也不能跑本机脚本。所以面板的重活交给这个本地服务做，网页只负责界面。

用法：
    python serve.py                 # 默认 http://127.0.0.1:8911
    python serve.py --port 9000
    python serve.py --open          # 启动后自动打开浏览器

安全边界（刻意的）：
- 只绑定 127.0.0.1，不监听外网。别人访问不到你的机器。
- 不提供任何「写入电商平台」的接口：改价 / 上架 / 投放 / 发消息一律没有。
- 抓取参数（站点 / 类目）走白名单校验，不接受任意 URL，避免被当成通用代理。
- 只用 Python 标准库，不引入新依赖。
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
DATA = BASE / "data"
DOCS = BASE / "docs"
sys.path.insert(0, str(BASE))

from src.calculator import load_products, load_yaml, score_all, calculate_unit_profit  # noqa: E402
from src.monitor import compare_snapshots                                              # noqa: E402
from src.ingest import ingest_csv, query_snapshot_dates                                # noqa: E402
from src.titleparse import describe as describe_title                          # noqa: E402
from src.sourcing import (SupplierQuote, compare_quotes, compare_summary,      # noqa: E402
                          load_quotes, save_quotes, KNOWN_PLATFORMS,
                          DEFAULT_VAT_RATE, QUOTE_COLUMNS, _parse_tiers, _as_bool, _as_float)

# ── 抓取约束 ──
# 站点是严格白名单。类目 slug 各站不同（例：玩具在美国站是 toys-and-games 而不是 toys），
# 所以不做硬编码白名单——那会给面板塞一堆用不了的选项。
# 改为「安全格式校验」：只允许小写字母数字与连字符，长度受限。
# 这样既能用你在榜单页地址栏看到的真实 slug，又不会变成任意 URL 代理。
SLUG_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def load_sites():
    """站点清单从 data/sites.yaml 读，不再硬编码 —— 用户可自由增删。"""
    f = DATA / "sites.yaml"
    if not f.exists():
        return {"us": {"domain": "www.amazon.com", "currency": "USD", "verified": True}}
    return load_yaml(str(f)) or {}


def enabled_sites():
    """enabled 显式为 false 的站点不出现在下拉里（那些需要先改抓取工具配置）。"""
    return {k: v for k, v in load_sites().items()
            if (v or {}).get("enabled", True) is not False}


# 类目中文名 → slug 的对照、已验证清单、已知不可用清单，全部来自
# data/category_aliases.yaml，不再硬编码 —— 用户可自由增删。
#
# ⚠️ 不能用机器翻译代替这张表。Amazon 的 slug 是固定标识符不是译名：
#    家居厨房=kitchen、运动户外=sporting-goods、电脑=pc、工具家装=hi。
def load_category_aliases():
    f = DATA / "category_aliases.yaml"
    if not f.exists():
        return {}
    return load_yaml(str(f)) or {}


def verified_categories():
    """{site: [slug,...]} —— 实测抓到过商品的 slug。"""
    return {k: list(v or []) for k, v in
            (load_category_aliases().get("verified") or {}).items()}


def known_bad_categories():
    """{site: [slug,...]} —— 实测确认抓不到商品的 slug，抓之前就能警告。"""
    return {k: list(v or []) for k, v in
            (load_category_aliases().get("known_bad") or {}).items()}


def category_choices(site):
    """给面板下拉用：该站可选的「中文名 → slug」清单，带验证状态。"""
    cfg = load_category_aliases()
    table = dict(cfg.get("default") or {})
    table.update((cfg.get("sites") or {}).get(site) or {})
    ok = set(verified_categories().get(site) or [])
    bad = set(known_bad_categories().get(site) or [])
    out = []
    for zh, slug in table.items():
        if not slug:
            continue
        out.append({"zh": zh, "slug": slug,
                    "verified": slug in ok, "known_bad": slug in bad})
    out.sort(key=lambda x: (not x["verified"], x["zh"]))
    return out


def resolve_category(raw, site):
    """把用户输入解析成 slug。中文名、同义词、或直接写 slug 都接受。

    返回 (slug, info)。info 里说明是怎么解析出来的、验证状态如何，
    让界面能把「你填的中文 → 实际要抓的 slug」显式摊开给用户看，
    而不是偷偷替换掉。
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError("类目不能为空")

    cfg = load_category_aliases()
    table = dict(cfg.get("default") or {})
    table.update((cfg.get("sites") or {}).get(site) or {})
    synonyms = cfg.get("synonyms") or {}

    lowered = text.lower()
    matched_by, zh = None, None

    if SLUG_RE.match(lowered):
        # 本来就是 slug，原样用 —— 不做任何替换
        slug, matched_by = lowered, "slug"
    else:
        # 当作中文名处理：先查同义词归一到标准名，再查对照表
        canonical = synonyms.get(text, text)
        if canonical in table and table[canonical]:
            slug, zh, matched_by = table[canonical], canonical, (
                "synonym" if canonical != text else "alias")
        else:
            names = sorted(table)
            raise ValueError(
                "没有「%s」的类目对照。可以：\n"
                "  ① 直接填 slug（小写字母/数字/连字符），比如 kitchen\n"
                "  ② 在 data/category_aliases.yaml 里加一条「%s: 对应slug」\n"
                "     slug 去目标站榜单页地址栏 /gp/bestsellers/<这一段>/ 看真实值\n"
                "  已有的中文名：%s"
                % (text, text, "、".join(names) if names else "（对照表是空的）"))

    if not SLUG_RE.match(slug):
        raise ValueError("对照表里「%s」对应的 slug 格式不合法：%s" % (zh or text, slug))

    ok = set(verified_categories().get(site) or [])
    bad = set(known_bad_categories().get(site) or [])
    warning = None
    if slug in bad:
        warning = ("%s 站实测确认 %s 抓不到商品（页面能打开但没有榜单元素）。"
                   "建议换一个，或去榜单页确认真实 slug。" % (site.upper(), slug))
    elif slug not in ok:
        warning = ("%s 站的 %s 没有实测验证过，第一次用请做好失败的准备。"
                   % (site.upper(), slug))

    return slug, {"input": text, "slug": slug, "zh": zh,
                  "matched_by": matched_by, "verified": slug in ok,
                  "known_bad": slug in bad, "warning": warning}


MAX_PAGES = 3          # 单次最多 3 页，防止无节制抓取
MIN_DELAY = 3.0        # 页面间隔下限（秒），不允许调更小

JOBS = {}              # job_id -> {status, log, result, started, finished}
JOBS_LOCK = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──────────────────────────────────────────────────────────────
# 业务处理
# ──────────────────────────────────────────────────────────────

def api_health():
    amzrank = find_amzrank()
    return {
        "ok": True,
        "mode": "local",
        "version": "1.0",
        "capabilities": {
            "scrape": bool(amzrank),
            "import": True,
            "monitor": True,
            "workflow": True,
            "listing_prompt": True,
            "supplier_compare": True,
            "score": True,
            "profit": True,
        },
        "amzrank_path": str(amzrank) if amzrank else None,
        "sites": enabled_sites(),
        "all_sites": load_sites(),
        "allowed_sites": sorted(enabled_sites().keys()),
        "verified_categories": verified_categories(),
        "known_bad_categories": known_bad_categories(),
        "category_choices": {s: category_choices(s) for s in enabled_sites()},
        "list_types": LIST_TYPES,
        "slug_hint": "类目 slug 各站不同。抓不到时去目标站榜单页，看地址栏 /gp/bestsellers/<这一段>/ 的真实值",
        "market_currency": MARKET_CURRENCY,
        "default_fx": DEFAULT_FX,
        "currency_note": "成本模型以人民币计价；平台售价为当地货币。从快照导入候选品时按汇率换算。"
                         "默认汇率是占位量级，不是实时汇率。",
        "snapshot_dates": query_snapshot_dates(str(DATA / "history.db")),
        "note": "改价 / 上架 / 投放 / 发消息：本服务不提供任何此类接口",
    }


def find_amzrank():
    """找 amzrank 抓取脚本。按常见相对位置找，找不到返回 None。"""
    candidates = [
        BASE.parent / "amzrank-stage" / "scraper" / "amzrank.py",
        BASE / "amzrank" / "amzrank.py",
        BASE.parent / "amzrank" / "scraper" / "amzrank.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def api_profit(body):
    products = {p.sku: p for p in load_products(str(DATA / "products.csv"))}
    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))

    sku = body.get("sku")
    if sku not in products:
        raise ValueError("找不到 SKU：%s" % sku)

    r = calculate_unit_profit(
        products[sku], platform_cfg, logistics_cfg,
        platform=body.get("platform", "tiktok_shop"),
        market=body.get("market", "US"),
        scenario=body.get("scenario", "standard"),
        price=body.get("price"),
    )
    return r.__dict__


def api_score(body):
    products = load_products(str(DATA / "products.csv"))
    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))
    results = score_all(products, platform_cfg, logistics_cfg,
                        platform=body.get("platform", "tiktok_shop"),
                        market=body.get("market", "US"),
                        scenario=body.get("scenario", "standard"))
    return [r.__dict__ for r in results]


def api_monitor(body):
    a, b = body.get("from"), body.get("to")
    if not (a and b):
        raise ValueError("需要 from 和 to 两个快照文件路径")
    pa, pb = (BASE / a).resolve(), (BASE / b).resolve()
    for p in (pa, pb):
        if BASE not in p.parents and p != BASE:
            raise ValueError("路径越界：%s" % p)
        if not p.exists():
            raise ValueError("文件不存在：%s" % p)
    changes, warning = compare_snapshots(str(pa), str(pb))
    return {
        "warning": warning,
        "items": [c.__dict__ for c in changes],
    }


def api_listing_prompt(body):
    """把三层 Prompt 拼成可直接粘贴到 AI 对话框的文本。
    **本服务不调用任何 LLM API** —— 不需要 API Key，也不会把你的数据发给第三方。
    生成的 Prompt 由你自己粘到 Claude / ChatGPT 里跑。
    """
    sk = BASE / "skills" / "listing"
    layer = body.get("layer", "planning")
    files = {
        "planning": "planning_layer.md",
        "amazon": "execution_amazon.md",
        "shopify": "execution_shopify.md",
        "tiktok": "execution_tiktok.md",
        "qa": "qa_layer.md",
    }
    if layer not in files:
        raise ValueError("未知层级：%s，可选 %s" % (layer, list(files)))

    tpl = (sk / files[layer]).read_text(encoding="utf-8")
    payload = body.get("payload")
    tail = ""
    if payload:
        tail = "\n\n---\n\n## 本次输入\n\n```json\n%s\n```\n" % json.dumps(
            payload, ensure_ascii=False, indent=2)
    return {
        "layer": layer,
        "prompt": tpl + tail,
        "note": "本服务不调用 LLM、不需要 API Key。请把这段 Prompt 粘到你自己的 AI 对话框里运行。",
    }


# ── 长任务：抓取 / 工作流 ──

def start_job(fn, *args):
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "log": [], "result": None,
                        "started": now_iso(), "finished": None}

    def runner():
        try:
            result = fn(job_id, *args)
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["result"] = result
        except Exception as e:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["result"] = {"error": "%s: %s" % (type(e).__name__, e)}
        finally:
            with JOBS_LOCK:
                JOBS[job_id]["finished"] = now_iso()

    threading.Thread(target=runner, daemon=True).start()
    return job_id


def joblog(job_id, line):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id]["log"].append("[%s] %s" % (time.strftime("%H:%M:%S"), line))


# 三种榜单，选品意义完全不同。
# 热销榜是「已经被占住的位置」——实测美国站办公用品前 68 名里
# 76% 是大牌或 Amazon 自有品牌，新手从这里选品等于挑最强的对手打。
# 新品榜和飙升榜看的是「正在起量的」，缺口更可能还在。
LIST_TYPES = {
    "bestsellers": "热销榜 —— 已经卖爆的，位置基本被占住了",
    "new": "新品榜 —— 最近上架且卖得动的，适合找还没被占的缺口",
    "movers": "飙升榜 —— 排名涨得最快的，适合抓短期趋势",
}


def run_scrape(job_id, site, category, pages, delay, list_key="bestsellers"):
    amzrank = find_amzrank()
    if not amzrank:
        raise RuntimeError("找不到 amzrank.py。请把抓取脚本放到 ../amzrank-stage/scraper/ 下")

    joblog(job_id, "启动抓取：%s / %s / %s / %d 页 / 间隔 %.1fs"
           % (site, category, list_key, pages, delay))
    cmd = [sys.executable, str(amzrank), "--site", site, "--category", category,
           "--list", list_key, "--pages", str(pages), "--delay", str(delay)]
    proc = subprocess.run(cmd, cwd=str(amzrank.parent), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=900)
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            joblog(job_id, line.strip())
    if proc.returncode != 0:
        joblog(job_id, "抓取进程退出码 %d" % proc.returncode)
        for line in (proc.stderr or "").splitlines()[-6:]:
            joblog(job_id, "stderr: " + line.strip())
        raise RuntimeError("抓取失败，见日志")

    joblog(job_id, "抓取完成，开始转换为标准快照格式")
    from adapters.amzrank_adapter import convert, latest_amzrank_output
    src = latest_amzrank_output(str(amzrank.parent / "amzrank_out"))
    date = datetime.now().strftime("%Y-%m-%d")
    # 榜单类型必须进文件名和快照日期，否则同一天抓热销榜和新品榜会互相覆盖。
    # bestsellers 不加后缀：它是默认值，也是文档里一直用的命名。
    suffix = "" if list_key == "bestsellers" else "_" + list_key
    out = DATA / "real" / ("competitors_%s_%s%s_%s.csv" % (site, category, suffix, date))
    count = convert(src, str(out), date, platform="amazon")

    # 让快照的 category 带上榜单类型，这样「拿热销榜比新品榜」会被现成的
    # 类目一致性守卫直接拦下 —— 那是无效对比：两个榜的商品本来就不是一批。
    if list_key != "bestsellers":
        import csv as _csv
        rows = list(_csv.DictReader(out.open(encoding="utf-8-sig")))
        if rows:
            for r in rows:
                r["category"] = "%s@%s" % (r.get("category") or category, list_key)
            with out.open("w", newline="", encoding="utf-8-sig") as fh:
                w = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
    joblog(job_id, "已转换 %d 条 -> %s" % (count, out.name))

    n = ingest_csv(str(out), "%s-%s%s-%s" % (site, category, suffix.replace("_", "-"), date),
                   str(DATA / "history.db"))
    joblog(job_id, "已入库 %d 条" % n)

    return {
        "rows": count,
        "csv": str(out.relative_to(BASE)).replace("\\", "/"),
        "snapshot_date": "%s-%s-%s" % (site, category, date),
        "source_file": Path(src).name,
    }


def run_workflow(job_id, input_csv, date, prev_date):
    joblog(job_id, "运行每日工作流：%s（对比 %s）" % (date, prev_date))
    cmd = [sys.executable, str(BASE / "automation" / "daily_workflow.py"),
           "--input", input_csv, "--date", date, "--prev-date", prev_date]
    proc = subprocess.run(cmd, cwd=str(BASE), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300)
    for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
        if line.strip():
            joblog(job_id, line.strip())
    if proc.returncode != 0:
        raise RuntimeError("工作流失败，见日志")
    report = BASE / "reports" / ("daily_%s.md" % date)
    return {
        "report": str(report.relative_to(BASE)).replace("\\", "/") if report.exists() else None,
        "content": report.read_text(encoding="utf-8") if report.exists() else None,
    }


def api_scrape(body):
    site = str(body.get("site", "us")).lower()
    pages = int(body.get("pages", 1))
    delay = float(body.get("delay", MIN_DELAY))

    sites = enabled_sites()
    if site not in sites:
        raise ValueError("站点 %s 未启用。可用：%s。"
                         "要加新站点，编辑 data/sites.yaml（并确认抓取工具支持该站）"
                         % (site, ", ".join(sorted(sites))))
    # 中文名、同义词、或直接写 slug 都接受 —— 解析结果会原样回给前端展示，
    # 不偷偷替换，用户始终知道实际抓的是哪个 slug。
    category, cat_info = resolve_category(body.get("category", "pet-supplies"), site)
    list_key = str(body.get("list", "bestsellers")).lower()
    if list_key not in LIST_TYPES:
        raise ValueError("未知榜单类型 %s，可选：%s"
                         % (list_key, "、".join("%s（%s）" % (k, v.split(" ——")[0])
                                                for k, v in LIST_TYPES.items())))
    pages = max(1, min(MAX_PAGES, pages))
    delay = max(MIN_DELAY, delay)     # 不允许低于 3 秒

    job_id = start_job(run_scrape, site, category, pages, delay, list_key)
    return {"job_id": job_id, "site": site, "category": category, "list": list_key,
            "list_label": LIST_TYPES[list_key],
            "pages": pages, "delay": delay, "category_info": cat_info}


def api_resolve_category(body):
    """让前端在你还没点「开始抓取」时就能看到中文会解析成哪个 slug。"""
    site = str(body.get("site", "us")).lower()
    try:
        _, info = resolve_category(body.get("category", ""), site)
        return {"ok": True, **info}
    except ValueError as e:
        # 用 reason 而不是 error：「没有这个中文名」是正常结果，不是服务出错。
        # 前端的 api() 包装器见到 error 字段会直接抛异常，消息就被吞掉了。
        return {"ok": False, "reason": str(e)}


def api_workflow(body):
    input_csv = body.get("input") or "data/competitors_2026-09-11.csv"
    p = (BASE / input_csv).resolve()
    if not p.exists():
        raise ValueError("输入文件不存在：%s" % input_csv)
    date = body.get("date") or datetime.now().strftime("%Y-%m-%d")
    prev = body.get("prev_date")
    if not prev:
        raise ValueError("需要 prev_date（用于对比的上一个快照日期）")
    job_id = start_job(run_workflow, str(p), date, prev)
    return {"job_id": job_id}


def api_job(job_id):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        return dict(j) if j else {"error": "找不到任务 %s" % job_id}


def api_data():
    """面板启动数据。直接现算，不依赖 build_dashboard.py 预生成的文件。"""
    import build_dashboard as bd
    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))
    real = bd.read_csv_rows(DATA / "real" / "competitors_real.csv")
    return {
        "mode": "local",
        "platforms": platform_cfg,
        "logistics": logistics_cfg,
        "margin_scenarios": {"conservative": 0.20, "standard": 0.30, "aggressive": 0.40},
        "products": bd.export_products(),
        "scores": bd.export_scores(platform_cfg, logistics_cfg),
        "competitors_demo": bd.read_csv_rows(DATA / "competitors_2026-09-11.csv"),
        "changes_demo": bd.export_changes(),
        "competitors_real": real or None,
        "changes_real": bd.export_real_changes(),
    }


def api_snapshots():
    """列出可用的快照 CSV，供面板下拉选择。"""
    out = []
    for d in (DATA, DATA / "real"):
        if not d.exists():
            continue
        for f in sorted(d.glob("competitors*.csv")):
            out.append({
                "path": str(f.relative_to(BASE)).replace("\\", "/"),
                "name": f.name,
                "rows": max(0, sum(1 for _ in f.open(encoding="utf-8-sig")) - 1),
                "real": "real" in f.parts,
            })
    return {"snapshots": out,
            "db_dates": query_snapshot_dates(str(DATA / "history.db"))}


# ── 候选商品读写（把抓到的竞品转成可评分的候选品）──

# ⚠️ 币种约定：成本模型全部以人民币计价（采购价来自 1688 等国内渠道，物流费率也是人民币报价）。
# 但抓取到的平台售价是当地货币（美/欧/日元）。两者直接相减会得出完全错误的结论，
# 所以从快照导入候选品时必须做汇率换算。
MARKET_CURRENCY = {"US": "USD", "EU": "EUR", "SEA": "USD", "JP": "JPY",
                   "UK": "GBP", "DE": "EUR"}
# 默认汇率仅为占位量级，**不是实时汇率**，使用前必须自行核实当日汇率。
DEFAULT_FX = {"USD": 7.1, "EUR": 7.7, "JPY": 0.048, "GBP": 9.0}

PRODUCT_COLUMNS = ["sku", "name", "category", "cost_price", "packaging_cost",
                   "weight_kg", "volume_l", "compliance_flag", "demand_score",
                   "gap_score", "logistics_score", "content_score", "planned_price"]

# 抓取拿不到、必须人工填的字段。UI 会据此标注。
MANUAL_ONLY_FIELDS = ["cost_price", "packaging_cost", "weight_kg", "volume_l",
                      "demand_score", "gap_score", "logistics_score", "content_score"]


def api_products_get():
    import csv as _csv
    f = DATA / "products.csv"
    rows = list(_csv.DictReader(f.open(encoding="utf-8-sig"))) if f.exists() else []
    return {
        "columns": PRODUCT_COLUMNS,
        "manual_only": MANUAL_ONLY_FIELDS,
        "manual_note": "采购价 / 包装 / 重量 / 体积抓不到——那是供应链数据，需要去 1688 等渠道问供应商报价。"
                       "四项打分是运营自己的判断，系统不代填。",
        "rows": rows,
    }


def api_products_save(body):
    """整表覆盖写入 products.csv。前端负责编辑，这里只做校验与落盘。
    写前自动备份，避免手滑覆盖掉已有数据。
    """
    import csv as _csv
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows 必须是非空数组")

    cleaned, seen = [], set()
    for i, r in enumerate(rows):
        sku = str(r.get("sku", "")).strip()
        if not sku:
            raise ValueError("第 %d 行缺少 sku" % (i + 1))
        if sku in seen:
            raise ValueError("sku 重复：%s" % sku)
        seen.add(sku)

        flag = str(r.get("compliance_flag", "ok")).strip() or "ok"
        if flag not in ("ok", "review_needed", "banned"):
            raise ValueError("%s 的 compliance_flag 只能是 ok / review_needed / banned" % sku)

        out = {"sku": sku,
               "name": str(r.get("name", "")).strip() or sku,
               "category": str(r.get("category", "")).strip() or "uncategorized",
               "compliance_flag": flag}
        # 数值字段：空值保持为空，不擅自填 0（0 和"未填"在业务上不是一回事）
        for k in ("cost_price", "packaging_cost", "weight_kg", "volume_l",
                  "demand_score", "gap_score", "logistics_score", "content_score",
                  "planned_price"):
            v = r.get(k)
            if v in (None, "", "null"):
                out[k] = ""
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                raise ValueError("%s 的 %s 不是数字：%r" % (sku, k, v))
        cleaned.append(out)

    f = DATA / "products.csv"
    backup = None
    if f.exists():
        backup = DATA / ("products.backup-%s.csv" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        backup.write_bytes(f.read_bytes())

    with f.open("w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=PRODUCT_COLUMNS)
        w.writeheader()
        w.writerows(cleaned)

    incomplete = [r["sku"] for r in cleaned
                  if r["cost_price"] == "" or r["planned_price"] == ""]
    return {
        "saved": len(cleaned),
        "backup": backup.name if backup else None,
        "incomplete": incomplete,
        "warning": ("以下候选品缺采购价或计划售价，评分时会被判为无法测算："
                    + "、".join(incomplete)) if incomplete else None,
    }


def api_candidates_from_snapshot(body):
    """把某份竞品快照里勾选的行，转成待填的候选品骨架。
    只搬抓得到的字段（名称、售价作为计划售价参考），抓不到的一律留空。
    """
    import csv as _csv
    path = body.get("snapshot")
    ids = body.get("item_ids") or []
    if not path:
        raise ValueError("需要 snapshot（快照 CSV 相对路径）")
    p = (BASE / path).resolve()
    if BASE not in p.parents or not p.exists():
        raise ValueError("快照不存在或路径越界：%s" % path)

    rows = {r["item_id"]: r for r in _csv.DictReader(p.open(encoding="utf-8-sig"))}
    category = body.get("category", "").strip() or "uncategorized"

    # 币种换算：快照里的售价是平台当地货币，成本模型是人民币，必须换算
    market = str(body.get("market", "US")).upper()
    currency = body.get("currency") or MARKET_CURRENCY.get(market, "USD")
    try:
        fx = float(body.get("fx_rate") or DEFAULT_FX.get(currency, 1.0))
    except (TypeError, ValueError):
        raise ValueError("fx_rate 不是数字：%r" % body.get("fx_rate"))
    if fx <= 0:
        raise ValueError("fx_rate 必须大于 0")

    out = []
    for iid in ids:
        r = rows.get(iid)
        if not r:
            continue
        try:
            local_price = float(r.get("price"))
        except (TypeError, ValueError):
            local_price = None
        # 对标竞品定价作为起点，但换算成人民币后才能和成本比较
        planned = round(local_price * fx, 2) if local_price is not None else ""
        info = describe_title(r.get("title") or "")
        out.append({
            "sku": iid,
            "name": (r.get("title") or "")[:60],
            "category": category,
            "compliance_flag": "ok",
            "planned_price": planned,
            # 重量从标题里解析（`Cat Litter 40 lb` -> 18.1kg）。
            # 以前留空，用户点「填入示例数值」会被填成 0.5kg——
            # 40 磅的猫砂因此显示「评分通过」，而按真实重量是必然亏损的。
            # 解析值只是**起点，仍需核实**：标题里的 oz 可能是容量不是重量。
            "cost_price": "", "packaging_cost": "",
            "weight_kg": (info["weight_kg"] if info["weight_kg"] is not None else ""),
            "volume_l": "",
            "demand_score": "", "gap_score": "", "logistics_score": "", "content_score": "",
            "_local_price": local_price, "_currency": currency, "_fx_rate": fx,
            "_zh": info["zh"], "_spec": info["spec"], "_heavy": info["heavy"],
            "_weight_from_title": info["weight_kg"],
            "_ref_rating": r.get("rating"), "_ref_reviews": r.get("review_count"),
            "_ref_rank": r.get("rank"),
        })
    return {
        "candidates": out,
        "currency": currency, "fx_rate": fx,
        "note": "planned_price = 竞品当地售价 × 汇率 %.4f，已换算为人民币"
                "（成本模型以人民币计价，不换算会得出完全错误的结论）。"
                "⚠️ 该汇率是占位值，不是实时汇率，请自行核实当日汇率。"
                "采购价与重量必须你自己填——抓不到。" % fx,
    }


def api_snapshot_rows(body):
    """读一份快照的全部行，供前端勾选。"""
    import csv as _csv
    path = body.get("snapshot")
    p = (BASE / path).resolve() if path else None
    if not p or BASE not in p.parents or not p.exists():
        raise ValueError("快照不存在或路径越界：%s" % path)
    rows = list(_csv.DictReader(p.open(encoding="utf-8-sig")))
    # 给每行补中文品类提示与规格（重量/件数）。
    # 重量尤其重要：跨境成本模型里它权重很大，而它就写在标题里
    # （`Cat Litter 40 lb` = 18.1kg），以前完全没被用上。
    for r in rows:
        info = describe_title(r.get("title") or "")
        r["_zh"] = info["zh"]
        r["_spec"] = info["spec"]
        r["_heavy"] = info["heavy"]
        r["_weight_from_title"] = info["weight_kg"]
    return {"snapshot": path, "count": len(rows), "rows": rows,
            "heavy_kg": __import__("src.titleparse", fromlist=["HEAVY_KG"]).HEAVY_KG}


# ── 供应商报价与比价 ──
# 说明：不抓取任何供货平台。实测 1688 / Alibaba / 义乌购 / DHgate 的价格全在
# 登录墙或反爬后面（1688 正文仅返回 97 字符、AliExpress 撞 Sign in 墙），
# 且项目边界规定遇到登录墙即停止自动访问。报价靠人工录入或平台自己的导出文件。

QUOTES_FILE = DATA / "suppliers.csv"


def api_quotes_get():
    quotes = load_quotes(str(QUOTES_FILE))
    return {
        "columns": QUOTE_COLUMNS,
        "platforms": KNOWN_PLATFORMS,
        "vat_rate": DEFAULT_VAT_RATE,
        "count": len(quotes),
        "rows": [{
            "sku": q.sku, "platform": q.platform, "supplier": q.supplier,
            "unit_price": q.unit_price, "moq": q.moq,
            "tax_included": q.tax_included, "freight_included": q.freight_included,
            "domestic_freight": q.domestic_freight, "sample_fee": q.sample_fee,
            "mold_fee": q.mold_fee, "lead_days": q.lead_days,
            "tiers": ";".join("%d:%s" % (a, b) for a, b in q.tiers),
            "url": q.url, "quoted_date": q.quoted_date, "notes": q.notes,
        } for q in quotes],
        "note": "本工具不抓取供货平台报价——那些价格在登录墙后面，且多为「面议」。"
                "报价请人工录入，或从平台自己的导出文件导入。",
    }


def _row_to_quote(r):
    return SupplierQuote(
        sku=str(r.get("sku", "")).strip(),
        platform=str(r.get("platform", "") or "其他").strip(),
        supplier=str(r.get("supplier", "")).strip(),
        unit_price=_as_float(r.get("unit_price")),
        moq=max(1, int(_as_float(r.get("moq"), 1))),
        tax_included=_as_bool(r.get("tax_included"), True),
        freight_included=_as_bool(r.get("freight_included"), False),
        domestic_freight=_as_float(r.get("domestic_freight")),
        sample_fee=_as_float(r.get("sample_fee")),
        mold_fee=_as_float(r.get("mold_fee")),
        lead_days=int(_as_float(r.get("lead_days"))) if str(r.get("lead_days") or "").strip() else None,
        tiers=_parse_tiers(r.get("tiers")),
        url=str(r.get("url", "")).strip(),
        quoted_date=str(r.get("quoted_date", "")).strip(),
        notes=str(r.get("notes", "")).strip(),
    )


def api_quotes_save(body):
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows 必须是数组")
    quotes = []
    for i, r in enumerate(rows):
        if not str(r.get("sku", "")).strip():
            raise ValueError("第 %d 行缺少 sku" % (i + 1))
        if _as_float(r.get("unit_price")) <= 0:
            raise ValueError("第 %d 行（%s / %s）单价必须大于 0"
                             % (i + 1, r.get("platform"), r.get("supplier")))
        quotes.append(_row_to_quote(r))

    backup = None
    if QUOTES_FILE.exists():
        backup = DATA / ("suppliers.backup-%s.csv" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        backup.write_bytes(QUOTES_FILE.read_bytes())
    n = save_quotes(quotes, str(QUOTES_FILE))
    return {"saved": n, "backup": backup.name if backup else None}


def api_compare_suppliers(body):
    """比价。报价可以直接传进来（未保存也能比），不传就读文件里该 SKU 的全部报价。"""
    sku = str(body.get("sku", "")).strip()
    qty = int(_as_float(body.get("order_qty"), 0))
    if qty <= 0:
        raise ValueError("order_qty 必须大于 0")
    need_invoice = bool(body.get("need_invoice"))
    vat = _as_float(body.get("vat_rate"), DEFAULT_VAT_RATE)

    inline = body.get("quotes")
    if isinstance(inline, list) and inline:
        quotes = [_row_to_quote(r) for r in inline]
    else:
        if not sku:
            raise ValueError("需要 sku（或直接传 quotes）")
        quotes = [q for q in load_quotes(str(QUOTES_FILE)) if q.sku == sku]
    if not quotes:
        return {"ok": False, "reason": "没有找到 %s 的报价" % (sku or "该商品")}

    results = compare_quotes(quotes, qty, need_invoice=need_invoice, vat_rate=vat)
    return {
        "ok": True,
        "order_qty": qty, "need_invoice": need_invoice, "vat_rate": vat,
        "summary": compare_summary(results),
        "results": [{
            "platform": r.quote.platform, "supplier": r.quote.supplier,
            "unit_price": r.quote.unit_price, "moq": r.quote.moq,
            "tax_included": r.quote.tax_included,
            "freight_included": r.quote.freight_included,
            "lead_days": r.quote.lead_days,
            "actual_qty": r.actual_qty, "tier_price": r.tier_price,
            "taxed_price": r.taxed_price,
            "freight_per_unit": r.freight_per_unit,
            "oneoff_per_unit": r.oneoff_per_unit,
            "landed_unit_cost": r.landed_unit_cost,
            "moq_shortfall": r.moq_shortfall,
            "warnings": r.warnings, "url": r.quote.url,
            "quoted_date": r.quote.quoted_date, "notes": r.quote.notes,
        } for r in results],
    }


def api_apply_cost(body):
    """把选中的到仓成本单价写回 products.csv 的 cost_price —— 打通比价到选品评分。"""
    import csv as _csv
    sku = str(body.get("sku", "")).strip()
    cost = _as_float(body.get("cost_price"), -1)
    if not sku:
        raise ValueError("需要 sku")
    if cost <= 0:
        raise ValueError("cost_price 必须大于 0")

    f = DATA / "products.csv"
    if not f.exists():
        raise ValueError("products.csv 不存在，请先在选品工作台建立候选品")
    rows = list(_csv.DictReader(f.open(encoding="utf-8-sig")))
    hit = False
    for r in rows:
        if r.get("sku") == sku:
            r["cost_price"] = cost
            hit = True
    if not hit:
        raise ValueError("products.csv 里没有 SKU %s —— 请先在选品工作台加入该候选品" % sku)

    backup = DATA / ("products.backup-%s.csv" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.write_bytes(f.read_bytes())
    with f.open("w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=PRODUCT_COLUMNS)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in PRODUCT_COLUMNS} for r in rows])
    return {"sku": sku, "cost_price": cost, "backup": backup.name,
            "note": "已写入采购价。到「选品工作台」第③步或「选品评分」页看重算后的结果。"}


# ── 配置读写（平台费率 / 物流市场 / 抓取站点）──
# 这三类清单原来硬编码在代码里，导致「不能自定义」。现在全部落在 data/*.yaml，
# 并通过下面的接口让面板直接编辑，不需要动代码。

CONFIG_FILES = {
    "platforms": ("platforms.yaml", "平台佣金与支付费率"),
    "logistics": ("logistics_rates.yaml", "各目的市场头程物流费率"),
    "sites": ("sites.yaml", "抓取站点"),
    "categories": ("category_aliases.yaml", "类目中文名对照"),
}


def api_config_get(which):
    if which not in CONFIG_FILES:
        raise ValueError("未知配置：%s，可选 %s" % (which, list(CONFIG_FILES)))
    fname, label = CONFIG_FILES[which]
    f = DATA / fname
    return {
        "which": which, "file": fname, "label": label,
        "data": load_yaml(str(f)) if f.exists() else {},
        "raw": f.read_text(encoding="utf-8") if f.exists() else "",
    }


def api_config_save(body):
    """整段覆盖写入。写前备份、写后立刻用 yaml 解析校验，解析失败自动回滚。"""
    which = str(body.get("which", ""))
    if which not in CONFIG_FILES:
        raise ValueError("未知配置：%s" % which)
    fname, _ = CONFIG_FILES[which]
    f = DATA / fname

    raw = body.get("raw")
    data = body.get("data")
    if raw is None and data is None:
        raise ValueError("需要 raw（YAML 文本）或 data（对象）之一")

    if raw is None:
        import yaml as _y
        raw = _y.safe_dump(data, allow_unicode=True, sort_keys=False)

    backup = None
    if f.exists():
        backup = DATA / ("%s.backup-%s" % (fname, datetime.now().strftime("%Y%m%d-%H%M%S")))
        backup.write_bytes(f.read_bytes())

    f.write_text(raw, encoding="utf-8")
    try:
        parsed = load_yaml(str(f))
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("解析结果不是非空对象")
        # 平台配置还要校验必需字段，否则保存后所有计算都会崩
        if which == "platforms":
            for k, v in parsed.items():
                if not isinstance(v, dict):
                    raise ValueError("%s 不是对象" % k)
                for need in ("commission_rate", "payment_fee_rate"):
                    if need not in v:
                        raise ValueError("%s 缺少 %s" % (k, need))
        if which == "logistics":
            for k, v in parsed.items():
                for need in ("base_fee", "rate_per_kg"):
                    if need not in (v or {}):
                        raise ValueError("市场 %s 缺少 %s" % (k, need))
    except Exception as e:
        if backup:
            f.write_bytes(backup.read_bytes())   # 回滚，别让坏配置留在盘上
        raise ValueError("配置格式有误，已回滚：%s" % e)

    return {"saved": which, "file": fname, "keys": sorted(parsed.keys()),
            "backup": backup.name if backup else None}


ROUTES_GET = {
    "/api/health": lambda q: api_health(),
    "/api/data": lambda q: api_data(),
    "/api/snapshots": lambda q: api_snapshots(),
    "/api/job": lambda q: api_job(q.get("id", [""])[0]),
    "/api/products": lambda q: api_products_get(),
    "/api/quotes": lambda q: api_quotes_get(),
    "/api/config": lambda q: api_config_get(q.get("which", ["platforms"])[0]),
}
ROUTES_POST = {
    "/api/profit": api_profit,
    "/api/score": api_score,
    "/api/monitor": api_monitor,
    "/api/listing-prompt": api_listing_prompt,
    "/api/scrape": api_scrape,
    "/api/resolve-category": api_resolve_category,
    "/api/workflow": api_workflow,
    "/api/products/save": api_products_save,
    "/api/candidates": api_candidates_from_snapshot,
    "/api/snapshot-rows": api_snapshot_rows,
    "/api/quotes/save": api_quotes_save,
    "/api/compare-suppliers": api_compare_suppliers,
    "/api/apply-cost": api_apply_cost,
    "/api/config/save": api_config_save,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "cbops-local/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s %s\n" % (self.command, self.path.split("?")[0]))

    def _send(self, code, payload=None, ctype="application/json; charset=utf-8", raw=None):
        body = raw if raw is not None else json.dumps(
            payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 只给本机页面用；面板可能从 file:// 或别的本地端口打开
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ROUTES_GET:
            try:
                self._send(200, ROUTES_GET[u.path](parse_qs(u.query)))
            except Exception as e:
                self._send(400, {"error": "%s: %s" % (type(e).__name__, e)})
            return
        # 其余当静态文件伺服 docs/
        rel = u.path.lstrip("/") or "index.html"
        f = (DOCS / rel).resolve()
        if DOCS not in f.parents and f != DOCS:
            self._send(403, {"error": "路径越界"}); return
        if not f.is_file():
            self._send(404, {"error": "找不到 %s" % rel}); return
        types = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8", ".md": "text/markdown; charset=utf-8"}
        self._send(200, raw=f.read_bytes(),
                   ctype=types.get(f.suffix.lower(), "application/octet-stream"))

    def do_POST(self):
        u = urlparse(self.path)
        fn = ROUTES_POST.get(u.path)
        if not fn:
            self._send(404, {"error": "未知接口 %s" % u.path}); return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, fn(body))
        except Exception as e:
            self._send(400, {"error": "%s: %s" % (type(e).__name__, e)})


def main():
    ap = argparse.ArgumentParser(description="跨境运营副驾驶 · 本地伴随服务")
    ap.add_argument("--port", type=int, default=8911)
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    url = "http://127.0.0.1:%d/" % args.port
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)

    amz = find_amzrank()
    print("=" * 58)
    print("面板：%s" % url)
    print("接口：%sapi/health" % url)
    print("抓取能力：%s" % ("可用（%s）" % amz.name if amz else "不可用 —— 找不到 amzrank.py"))
    print("绑定：127.0.0.1（仅本机，外网访问不到）")
    print("不提供改价 / 上架 / 投放 / 发消息接口")
    print("=" * 58)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
