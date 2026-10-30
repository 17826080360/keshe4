# -*- coding: utf-8 -*-
"""
扫码高并发优化：溯源链路缓存。
优先使用 Redis（TTL 过期），Redis 不可用时自动回退到进程内缓存，
保证演示环境（无 Redis）也能展示"缓存命中/未命中"。
"""
import time
import threading

try:
    import redis as _redis
    _REDIS_AVAILABLE = True
except Exception:
    _REDIS_AVAILABLE = False


class LocalCache:
    """进程内 TTL 缓存（线程安全）。"""

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            if item["expire"] < time.time():
                self._store.pop(key, None)
                return None
            return item["value"]

    def set(self, key, value, ttl):
        with self._lock:
            self._store[key] = {"value": value, "expire": time.time() + ttl}


class CacheService:
    def __init__(self, host="127.0.0.1", port=6379, db=0, ttl=300):
        self.ttl = ttl
        self.redis = None
        self.local = LocalCache()
        self.backend = "memory"
        if _REDIS_AVAILABLE:
            try:
                self.redis = _redis.Redis(host=host, port=port, db=db,
                                          socket_connect_timeout=1, socket_timeout=1)
                self.redis.ping()
                self.backend = "redis"
            except Exception:
                self.redis = None
                self.backend = "memory"
        print(f"[缓存服务] 当前后端：{self.backend}（TTL={ttl}s）")

    def get(self, key):
        if self.redis is not None:
            try:
                v = self.redis.get(key)
                return v.decode("utf-8") if v else None
            except Exception:
                pass
        return self.local.get(key)

    def set(self, key, value, ttl=None):
        ttl = ttl or self.ttl
        if self.redis is not None:
            try:
                self.redis.setex(key, ttl, value)
                return
            except Exception:
                pass
        self.local.set(key, value, ttl)

    def backend_name(self):
        return "Redis" if self.backend == "redis" else "内存缓存"


cache = CacheService()
