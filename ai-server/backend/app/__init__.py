"""将迁移前的 ``backend.app`` 导入路径映射到当前根目录 app 包。"""
from pathlib import Path

# Python 会沿着这个路径寻找 backend.app.main、backend.app.models 等模块，
# 避免为兼容旧测试复制一套应用源码。
__path__ = [str(Path(__file__).resolve().parents[2] / "app")]
