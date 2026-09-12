import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

DATA = Path(__file__).parent / "data"


def _skus():
    """从 products.csv 实际读取 SKU。
    测试不能硬编码 TRAVEL-001 这类示例 SKU——用户换成自己的商品后测试会全红，
    而那不是代码坏了。
    """
    from src.calculator import load_products
    return load_products(str(DATA / "products.csv"))


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
