# -*- coding: utf-8 -*-
"""哈希工具：规范化内容 → SHA-256 指纹。链上存指纹，库中存明文。"""
import hashlib
import json


def canonical_json(content) -> str:
    """规范化：键排序 + 紧凑 JSON，保证同一内容哈希唯一。"""
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            content = {"text": content}
    if not isinstance(content, dict):
        content = {"value": content}
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(content) -> str:
    """返回 0x 前缀 64 位十六进制指纹。"""
    return "0x" + sha256_hex(canonical_json(content))


def bytes32_from_text(text: str) -> str:
    """把批次号等字符串编码为 bytes32（不足 32 字节右补零）。"""
    b = text.encode("utf-8")[:32]
    return "0x" + b.ljust(32, b"\x00").hex()
