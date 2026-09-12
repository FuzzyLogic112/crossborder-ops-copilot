import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

DATA = Path(__file__).parent / "data"

# 测试自带的数据，归 tests/ 所有。
# 为什么不用 data/ 下的文件：那是用户数据，`reset_data.py --all` 会清空它，
# 清完再跑测试会一片红——但那不是代码坏了。测试必须自给自足。
# data/ 下只有配置（platforms/logistics/sites/category_aliases）是测试可以依赖的，
# 因为重置脚本从不删配置。
FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def _skus():
    """从测试自带的 products.csv 读 SKU。

    以前读 data/products.csv，但那是用户会替换、也会被重置清空的文件。
    """
    from src.calculator import load_products
    return load_products(str(FIXTURES / "products.csv"))


@pytest.fixture(scope="session")
def viable_sku():
    """一个「按当前计划售价能盈利」的 SKU。
    不能只挑「非 banned」——真实数据里很多品按市场价是亏本的，
    那些品评分结果就是「淘汰」，用它们去断言「未被淘汰」必然失败。
    """
    from src.calculator import load_yaml, score_product
    pc = load_yaml(str(DATA / "platforms.yaml"))
    lc = load_yaml(str(DATA / "logistics_rates.yaml"))
    for p in _skus():
        if p.compliance_flag == "banned" or not p.planned_price:
            continue
        if not score_product(p, pc, lc).eliminated:
            return p.sku
    pytest.skip("products.csv 里没有按当前计划售价可盈利的商品")


@pytest.fixture(scope="session")
def any_sku():
    """任意一个能参与计算的 SKU（非 banned、有计划售价），可能是亏本品。"""
    for p in _skus():
        if p.compliance_flag != "banned" and p.planned_price:
            return p.sku
    pytest.skip("products.csv 里没有可用于计算的商品")


@pytest.fixture(scope="session")
def any_product():
    for p in _skus():
        if p.compliance_flag != "banned" and p.planned_price:
            return p
    pytest.skip("products.csv 里没有可用于计算的商品")


@pytest.fixture(autouse=True)
def _mcp_uses_fixture_data(request, tmp_path_factory, monkeypatch):
    """MCP 工具内部读的是生产路径 data/products.csv。

    `reset_data.py --all` 会把它清成只有表头——那是用户要的「完全空的环境」，
    但会让这些测试全红。所以给 MCP 测试单独搭一个临时 data 目录：
    products.csv 用测试自带的，配置 YAML 仍用真实的（测试要断言真实费率，
    而且重置脚本从不删配置）。
    """
    if "test_mcp" not in request.node.nodeid:
        return
    import shutil

    import mcp_server.tools as tools

    d = tmp_path_factory.mktemp("mcp-data")
    shutil.copy(FIXTURES / "products.csv", d / "products.csv")
    for name in ("platforms.yaml", "logistics_rates.yaml"):
        src = DATA / name
        if src.exists():
            shutil.copy(src, d / name)
    monkeypatch.setattr(tools, "DATA", d)
