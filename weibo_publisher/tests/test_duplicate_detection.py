"""
单元测试: 发布重复检测功能
测试 do_publish() 的 is_dup 返回值逻辑
"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path


# ============================================================
# 辅助: 模拟 gui 对象
# ============================================================
def make_gui(api_key="test-key", posted_dramas=None):
    """创建模拟的 gui 对象"""
    gui = MagicMock()
    gui.get_api.return_value = {
        "api_base": "https://api.test.com",
        "api_key": api_key,
        "model": "test-model",
    }
    gui.get_or_create_driver.return_value = MagicMock()
    gui.shared_driver = MagicMock()
    gui.shared_driver.is_alive.return_value = True
    gui.inp_post_tpl = MagicMock()
    gui.inp_post_tpl.toPlainText.return_value = "#{剧名}# {原名} {年份}\n{AI影评}#电视剧#"
    gui.inp_post_tpl_multi = MagicMock()
    gui.inp_post_tpl_multi.toPlainText.return_value = "#{剧名}# {原名}\n{AI影评}#电视剧#"
    gui.inp_comment_quark_tpl = MagicMock()
    gui.inp_comment_quark_tpl.text.return_value = "K👉{链接}"
    gui.inp_comment_baidu_tpl = MagicMock()
    gui.inp_comment_baidu_tpl.text.return_value = "D👉{链接}"
    return gui


def make_fields(drama="测试剧", original="Test Drama", poster="https://img.test.com/1.jpg"):
    """创建模拟的 fields 字典"""
    return {
        "drama": drama,
        "original": original,
        "year": "2024",
        "alias": "",
        "type": "剧情",
        "season": "",
        "episodes": "39",
        "poster": poster,
        "pan": "",
        "baidu": "",
        "tag": "电视剧",
    }


# ============================================================
# 测试: do_publish 重复检测
# ============================================================
class TestDoPublishDuplicateDetection:
    """测试 do_publish() 的重复检测逻辑"""

    @patch("app.load_memory")
    @patch("app.generate_review")
    @patch("app.download_poster")
    def test_already_posted_returns_is_dup(self, mock_download, mock_review, mock_memory):
        """已发布过的内容应返回 is_dup=True"""
        from app import do_publish

        mock_memory.return_value = {
            "posted_dramas": ["测试剧|Test Drama"],
            "last_fields": {},
        }
        gui = make_gui()
        fields = make_fields()

        success, fatal, is_dup = do_publish(gui, fields)

        assert is_dup is True
        assert success is False
        assert fatal is False
        # 不应调用 AI 影评和海报下载
        mock_review.assert_not_called()
        mock_download.assert_not_called()

    @patch("app.load_memory")
    @patch("app.generate_review", return_value="这是AI影评")
    @patch("app.download_poster", return_value="/tmp/test.jpg")
    def test_not_posted_continues_to_publish(self, mock_download, mock_review, mock_memory):
        """未发布过的内容应继续正常发布流程"""
        from app import do_publish

        mock_memory.return_value = {
            "posted_dramas": [],
            "last_fields": {},
        }
        gui = make_gui()
        fields = make_fields()

        # 模拟 driver.publish 返回成功
        gui.get_or_create_driver.return_value.publish.return_value = True

        success, fatal, is_dup = do_publish(gui, fields)

        assert is_dup is False
        # 应调用 AI 影评和海报下载
        mock_review.assert_called_once()
        mock_download.assert_called_once()

    @patch("app.load_memory")
    def test_empty_posted_dramas_not_dup(self, mock_memory):
        """空的 posted_dramas 列表不应触发重复检测"""
        from app import do_publish

        mock_memory.return_value = {
            "posted_dramas": [],
            "last_fields": {},
        }
        gui = make_gui()
        fields = make_fields()

        # 只测到 API Key 检查之前的逻辑
        # 由于后续需要 mock 很多东西，这里只验证 is_dup=False
        with patch("app.generate_review", return_value="影评"), \
             patch("app.download_poster", return_value="/tmp/test.jpg"):
            gui.get_or_create_driver.return_value.publish.return_value = True
            success, fatal, is_dup = do_publish(gui, fields)
            assert is_dup is False

    @patch("app.load_memory")
    def test_different_drama_not_dup(self, mock_memory):
        """不同的剧名不应触发重复检测"""
        from app import do_publish

        mock_memory.return_value = {
            "posted_dramas": ["已发布剧|Already Posted"],
            "last_fields": {},
        }
        gui = make_gui()
        fields = make_fields(drama="新剧", original="New Drama")

        with patch("app.generate_review", return_value="影评"), \
             patch("app.download_poster", return_value="/tmp/test.jpg"):
            gui.get_or_create_driver.return_value.publish.return_value = True
            success, fatal, is_dup = do_publish(gui, fields)
            assert is_dup is False

    @patch("app.load_memory")
    def test_same_drama_different_original_not_dup(self, mock_memory):
        """相同剧名但不同原名不应触发重复检测"""
        from app import do_publish

        mock_memory.return_value = {
            "posted_dramas": ["测试剧|Original A"],
            "last_fields": {},
        }
        gui = make_gui()
        fields = make_fields(drama="测试剧", original="Original B")

        with patch("app.generate_review", return_value="影评"), \
             patch("app.download_poster", return_value="/tmp/test.jpg"):
            gui.get_or_create_driver.return_value.publish.return_value = True
            success, fatal, is_dup = do_publish(gui, fields)
            assert is_dup is False

    @patch("app.load_memory")
    def test_no_memory_file_no_dup(self, mock_memory):
        """memory.json 不存在时不应触发重复检测"""
        from app import do_publish

        mock_memory.return_value = {
            "posted_dramas": [],
            "last_fields": {},
        }
        gui = make_gui()
        fields = make_fields()

        with patch("app.generate_review", return_value="影评"), \
             patch("app.download_poster", return_value="/tmp/test.jpg"):
            gui.get_or_create_driver.return_value.publish.return_value = True
            success, fatal, is_dup = do_publish(gui, fields)
            assert is_dup is False

    # ============================================================
    # 测试: 边界情况
    # ============================================================

    @patch("app.load_memory")
    def test_empty_drama_not_dup(self, mock_memory):
        """空剧名应返回 False, False, False（字段验证失败）"""
        from app import do_publish

        gui = make_gui()
        fields = make_fields(drama="")

        success, fatal, is_dup = do_publish(gui, fields)

        assert success is False
        assert fatal is False
        assert is_dup is False

    @patch("app.load_memory")
    def test_empty_poster_not_dup(self, mock_memory):
        """空海报 URL 应返回 False, False, False（字段验证失败）"""
        from app import do_publish

        gui = make_gui()
        fields = make_fields(poster="")

        success, fatal, is_dup = do_publish(gui, fields)

        assert success is False
        assert fatal is False
        assert is_dup is False

    def test_no_api_key_not_dup(self):
        """无 API Key 应返回 False, False, False"""
        from app import do_publish

        gui = make_gui(api_key="")
        fields = make_fields()

        success, fatal, is_dup = do_publish(gui, fields)

        assert success is False
        assert fatal is False
        assert is_dup is False


# ============================================================
# 测试: 返回值格式
# ============================================================
class TestDoPublishReturnFormat:
    """测试 do_publish() 返回值格式"""

    @patch("app.load_memory")
    def test_returns_tuple_of_three(self, mock_memory):
        """应返回三元组 (success, fatal, is_dup)"""
        from app import do_publish

        gui = make_gui(api_key="")
        fields = make_fields()

        result = do_publish(gui, fields)

        assert isinstance(result, tuple)
        assert len(result) == 3

    @patch("app.load_memory")
    def test_all_returns_are_three_tuples(self, mock_memory):
        """所有 return 路径都应返回三元组"""
        from app import do_publish

        # 测试空剧名路径
        gui = make_gui()
        fields = make_fields(drama="")
        r1 = do_publish(gui, fields)
        assert len(r1) == 3

        # 测试空海报路径
        fields = make_fields(poster="")
        r2 = do_publish(gui, fields)
        assert len(r2) == 3

        # 测试无 API Key 路径
        gui = make_gui(api_key="")
        fields = make_fields()
        r3 = do_publish(gui, fields)
        assert len(r3) == 3
