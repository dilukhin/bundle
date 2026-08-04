"""Совместимый фасад сериализации и публикации bundle."""

from bundle_serialize import build_fragment
from bundle_output import publish_append, publish_stdout, publish_write

__all__ = ["build_fragment", "publish_append", "publish_stdout", "publish_write"]
