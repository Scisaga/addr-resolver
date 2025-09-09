import unittest
import time
from util.address_db import (
    connect, insert_address, update_address, delete_address,
    search_address, find_nearby_addresses
)

class TestAddressDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_data = {
            "id": "unittest-001",
            "name": "六道口",
            "address": "北京市海淀区六道口西北角",
            "lat": 40.001,
            "lng": 116.341,
            "province": "北京市",
            "district": "海淀区",
            "township": "学院路街道",
            "tag": "单元测试",
            "comment": "初始备注"
        }
        insert_address(cls.test_data)

    def test_insert_missing_field(self):
        incomplete_data = {
            "id": "unittest-bad",
            "name": "",  # ⛔ 空 name
            "address": "某地",
            "lat": 39.9,
            "lng": 116.3
        }
        with self.assertRaises(ValueError):
            insert_address(incomplete_data)

    def test_search_by_keyword(self):
        results = search_address(query="六道口", page=1, page_size=5)
        self.assertTrue(any(r["id"] == self.test_data["id"] for r in results))

    def test_search_by_time_range(self):
        now = int(time.time())
        past = now - 3600
        results = search_address(start_ts=past, end_ts=now, page=1, page_size=5)
        self.assertTrue(any(r["id"] == self.test_data["id"] for r in results))

    def test_update_address(self):
        update_address(self.test_data["id"], {"comment": "更新备注"})
        results = search_address(query="六道口", page=1, page_size=1)
        self.assertEqual(results[0]["comment"], "更新备注")

    def test_find_nearby(self):
        results = find_nearby_addresses(40.001, 116.341, radius=300, page=1, page_size=5)
        self.assertTrue(any(r["id"] == self.test_data["id"] for r in results))

    @classmethod
    def tearDownClass(cls):
        delete_address(cls.test_data["id"])

if __name__ == "__main__":
    unittest.main()
