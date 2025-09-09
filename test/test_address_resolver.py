import unittest
from resolver import resolve_address, amap_geocode, amap_around_search, core_keyword_overlap_ratio, amap_poi_search, regeo

class TestAddressResolver(unittest.TestCase):

    def test_amap_geocode(self):
        print("🧪 测试 amap_geocode")
        city = "北京市"
        address = "方恒国际A座"
        location = amap_geocode(city, address)
        print(f"📍 输入地址: {city} {address}")
        print(f"📍 返回坐标: {location}")
        assert location, "amap_geocode 返回为空"

    def test_amap_poi_search(self):
        print("🧪 测试 amap_geocode")
        city = "北京市"
        address = "方恒国际A座"
        pois = amap_poi_search(city, address)
        print(pois)

    def test_amap_around_search(self):
        print("🧪 测试 amap_around_search")
        # 方恒国际A座中心点
        location = "116.481197,39.989751"
        keyword = "健身"
        pois = amap_around_search(location, keyword, radius=1000)
        print(f"🔍 周边搜索关键词: {keyword}")
        print(f"📋 命中 POI 数量: {len(pois)}")
        for i, poi in enumerate(pois[:5], start=1):
            print(f"{i}. {poi['name']} | {poi.get('address', '')}")
        assert pois, "amap_around_search 无结果"

    def test_aregeo(self):
        print("🧪 测试 amap_regeo")
        # 方恒国际A座中心点
        location = "116.481197,39.989751"
        info = regeo(location)
        print(info)

    def test_core_keyword_overlap_ratio(self):
        """基于关键词的相似度"""
        a = "朝阳区北苑小街8号院5号楼D区"
        b = "北苑小街8号5号楼D区"
        result = core_keyword_overlap_ratio(a, b)
        self.assertEqual(result, 100)

    def test_exact_match(self):
        """测试典型门牌地址能成功解析为高德 POI"""
        result = resolve_address("北京市朝阳区北苑小街8号院5号楼D区1层101室")
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)
        self.assertIn("address", result)
        self.assertGreater(len(result.get("name", "")), 0)
        self.assertGreater(len(result.get("address", "")), 0)

    def test_with_landmark(self):
        """测试带地标描述的地址能模糊匹配"""
        result = resolve_address("北京市朝阳区北苑小街8号院5号楼D区北侧")
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("name", "").startswith("5号楼"))

    def test_incomplete_address(self):
        """测试不完整地址仍然可以结构化并获得候选"""
        result = resolve_address("北苑小街8号院5号楼")
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)

    def test_similarity(self):
        """测试基于相似度拆选"""
        result = resolve_address("阿里巴巴望京A座高德")
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)

    def test_non_match(self):
        """测试明显无效的地址"""
        result = resolve_address("BBS-x-dsaf")
        self.assertEqual(result, {})  # 应该无结果

if __name__ == "__main__":
    unittest.main()