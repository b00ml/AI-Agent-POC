"""
差旅标准与城市档次数据管理

功能：
1. 缓存差旅标准（职级+城市档次→住宿/伙食/交通标准）
2. 缓存城市档次映射
3. 提供标准查询函数
"""

import os

from core.client import QihengClient
from data.config import DEFAULT_CITY_TIERS
from core.logger import get_logger

logger = get_logger("travel_data")


class TravelDataManager:
    """差旅数据管理器"""

    def __init__(self, client: QihengClient):
        self.client = client
        self._standards = None
        self._city_tiers = None
        self._standards_cache = {}
        self._city_cache = {}

    def load_data(self):
        """加载差旅标准和城市档次数据"""
        logger.info("正在加载差旅标准数据...")
        self._standards = self.client.travel_standards()
        self._build_standards_cache()

        logger.info("正在加载城市档次数据...")
        self._city_tiers = self.client.cities()
        self._build_city_cache()

        logger.info(f"✓ 加载完成：{len(self._standards)} 条差旅标准，{len(self._city_tiers)} 个城市")

    def _build_standards_cache(self):
        """构建差旅标准缓存索引"""
        self._standards_cache = {}
        for std in self._standards:
            key = (std['jobLevel'], std['cityTier'])
            self._standards_cache[key] = std

    def _build_city_cache(self):
        """构建城市档次缓存索引"""
        self._city_cache = {}
        for city in self._city_tiers:
            self._city_cache[city['name']] = city['tier']

        # 合并默认城市映射（用于API未包含的城市）
        for city, tier in DEFAULT_CITY_TIERS.items():
            if city not in self._city_cache:
                self._city_cache[city] = tier

    def get_city_tier(self, city_name: str) -> str:
        """获取城市档次"""
        if not city_name:
            return ''

        # 精确匹配
        if city_name in self._city_cache:
            return self._city_cache[city_name]

        # 模糊匹配（包含城市名）
        for name, tier in self._city_cache.items():
            if name in city_name or city_name in name:
                return tier

        # 未知城市：返回空串，由审核引擎按 FLAG 处理（不做默认档次的静默假设）
        return ''

    def has_city(self, city_name: str) -> bool:
        """城市是否在已知档次映射中"""
        if not city_name:
            return False
        if city_name in self._city_cache:
            return True
        for name in self._city_cache:
            if name in city_name or city_name in name:
                return True
        return False

    def get_standard(self, job_level: str, city_tier: str) -> dict:
        """获取指定职级和城市档次的差旅标准"""
        key = (job_level, city_tier)
        return self._standards_cache.get(key)

    def get_hotel_cap(self, job_level: str, city_tier: str) -> int:
        """获取住宿费标准（分/晚）"""
        std = self.get_standard(job_level, city_tier)
        return std['hotelCapPerNightFen'] if std else 0

    def get_meal_allowance(self, job_level: str, city_tier: str) -> int:
        """获取伙食补助标准（分/天）"""
        std = self.get_standard(job_level, city_tier)
        return std['mealAllowancePerDayFen'] if std else 0

    def get_city_transport(self, job_level: str, city_tier: str) -> int:
        """获取市内交通补助标准（分/天）"""
        std = self.get_standard(job_level, city_tier)
        return std['cityTransportPerDayFen'] if std else 0

    def get_long_distance_class(self, job_level: str, city_tier: str) -> str:
        """获取长途交通舱位标准"""
        std = self.get_standard(job_level, city_tier)
        return std['longDistanceClass'] if std else ''

    def list_standards(self) -> list:
        """列出所有差旅标准"""
        return self._standards or []

    def list_cities(self) -> list:
        """列出所有城市"""
        return self._city_tiers or []


# 全局实例
_global_manager = None


def get_travel_manager(client: QihengClient = None) -> TravelDataManager:
    """获取全局差旅数据管理器"""
    global _global_manager
    if _global_manager is None and client:
        _global_manager = TravelDataManager(client)
        _global_manager.load_data()
    return _global_manager


if __name__ == "__main__":
    import os
    from core.client import QihengClient

    api_key = os.environ['QIHENG_API_KEY']
    client = QihengClient(api_key=api_key)

    manager = TravelDataManager(client)
    manager.load_data()

    # 测试查询
    print("\n=== 测试差旅标准查询 ===")

    # 测试1: MANAGER / TIER1 住宿标准
    hotel_cap = manager.get_hotel_cap('MANAGER', 'TIER1')
    print(f"MANAGER / TIER1 住宿标准: {hotel_cap // 100}.{str(hotel_cap % 100).zfill(2)} 元/晚")

    # 测试2: STAFF / TIER2 伙食补助
    meal_allowance = manager.get_meal_allowance('STAFF', 'TIER2')
    print(f"STAFF / TIER2 伙食补助: {meal_allowance // 100}.{str(meal_allowance % 100).zfill(2)} 元/天")

    # 测试3: 上海城市档次
    shanghai_tier = manager.get_city_tier('上海')
    print(f"上海城市档次: {shanghai_tier}")

    # 测试4: 潍坊城市档次
    weifang_tier = manager.get_city_tier('潍坊')
    print(f"潍坊城市档次: {weifang_tier}")

    # 测试5: 未知城市默认档次
    unknown_tier = manager.get_city_tier('拉萨')
    print(f"未知城市档次: {unknown_tier}")
