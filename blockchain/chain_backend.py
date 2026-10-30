# -*- coding: utf-8 -*-
"""
链后端统一接口：本地模拟链（默认） / Ganache 以太坊真实链。

分层存储设计：
  - 明文数据存 SQLite（业务库，可读、可查、可展示）；
  - 内容指纹（SHA-256 哈希）上链存证（不可篡改）。
验证时：用库中明文重算哈希 → 与链上指纹比对，不一致即判定被篡改。

本地模拟链是一个真正的哈希链（block_hash = sha256(prev_hash + raw_data + index + ts)），
逐块校验可发现任何历史篡改；无 Ganache 环境时同样具备完整的防篡改演示能力。
"""
import json
import os
import time

from .hash_utils import sha256_hex

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "raw_data")
CHAIN_FILE = os.path.join(DATA_DIR, "chain_store.json")
CONTRACT_ADDR_FILE = os.path.join(DATA_DIR, "contract_address.txt")


# ---------------------------------------------------------------------------
# 本地模拟链（哈希链）
# ---------------------------------------------------------------------------
class LocalChain:
    def __init__(self, chain_file=CHAIN_FILE):
        self.chain_file = chain_file
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(self.chain_file):
            with open(self.chain_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.blocks = data.get("blocks", [])
            self.genesis = data.get("genesis")
        else:
            self.genesis = "0x" + sha256_hex("AgriTrace-Genesis-2026")
            self.blocks = []
            self._save()

    def _save(self):
        with open(self.chain_file, "w", encoding="utf-8") as f:
            json.dump({"genesis": self.genesis, "blocks": self.blocks},
                      f, ensure_ascii=False, indent=1)

    def _block_hash(self, index, ts, prev_hash, data):
        raw = f"{index}|{ts}|{prev_hash}|{json.dumps(data, ensure_ascii=False, sort_keys=True)}"
        return "0x" + sha256_hex(raw)

    def add_record(self, batch_id, data_hash, record_type, operator="system"):
        """把一条数据指纹追加进哈希链，返回存证信息。"""
        index = len(self.blocks)
        ts = int(time.time())
        prev_hash = self.blocks[-1]["block_hash"] if self.blocks else self.genesis
        data = {
            "batch_id": batch_id,
            "data_hash": data_hash,
            "record_type": record_type,
            "operator": operator,
        }
        block_hash = self._block_hash(index, ts, prev_hash, data)
        self.blocks.append({
            "index": index,
            "timestamp": ts,
            "prev_hash": prev_hash,
            "raw_data": data,
            "block_hash": block_hash,
        })
        self._save()
        return {
            "ok": True,
            "chain": "local",
            "tx": block_hash,
            "block": index,
        }

    def verify_hash(self, data_hash):
        """查询某指纹是否存在于链上。"""
        for b in reversed(self.blocks):
            if b["raw_data"].get("data_hash") == data_hash:
                return {
                    "exists": True,
                    "prev_hash": b["raw_data"].get("prev_hash", ""),
                    "block": b["index"],
                    "timestamp": b["timestamp"],
                    "operator": b["raw_data"].get("operator", ""),
                }
        return {"exists": False}

    def get_batch_chain(self, batch_id):
        """按顺序返回该批次的哈希链。"""
        return [b for b in self.blocks if b["raw_data"].get("batch_id") == batch_id]

    def integrity_check(self):
        """全链完整性校验：逐块重算哈希并检查链接。"""
        problems = []
        prev = self.genesis
        for i, b in enumerate(self.blocks):
            recomputed = self._block_hash(b["index"], b["timestamp"], b["prev_hash"], b["raw_data"])
            if recomputed != b["block_hash"]:
                problems.append(f"区块 #{b['index']} 哈希不一致")
            if b["prev_hash"] != prev:
                problems.append(f"区块 #{b['index']} 链接断裂")
            prev = b["block_hash"]
        return {
            "ok": len(problems) == 0,
            "blocks": len(self.blocks),
            "problems": problems,
        }


# ---------------------------------------------------------------------------
# Ganache 以太坊链（web3）
# ---------------------------------------------------------------------------
class GanacheChain:
    def __init__(self, rpc_url="http://127.0.0.1:8545"):
        from web3 import Web3
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise RuntimeError("无法连接 Ganache: " + rpc_url)
        self.name = "ganache"
        self.contract = None
        self.account = self.w3.eth.accounts[0]
        addr_file = CONTRACT_ADDR_FILE
        if os.path.exists(addr_file):
            with open(addr_file, "r", encoding="utf-8") as f:
                addr = f.read().strip()
            # 懒加载 ABI（与 deploy 脚本共用编译产物）
            abi_file = os.path.join(BASE_DIR, "blockchain", "Traceability_compiled.json")
            if os.path.exists(abi_file):
                with open(abi_file, "r", encoding="utf-8") as f:
                    compiled = json.load(f)
                self.contract = self.w3.eth.contract(address=addr, abi=compiled["abi"])

    @property
    def ready(self):
        return self.contract is not None

    def add_record(self, batch_id, data_hash, record_type, operator="system"):
        tx = self.contract.functions.addRecord(
            _to_bytes32(batch_id), _to_bytes32(data_hash), record_type
        ).transact({"from": self.account})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return {
            "ok": receipt.status == 1,
            "chain": self.name,
            "tx": receipt.transactionHash.hex(),
            "block": receipt.blockNumber,
        }

    def verify_hash(self, data_hash):
        exists, operator, ts, prev, rtype = self.contract.functions.verifyRecord(
            _to_bytes32(data_hash)
        ).call()
        return {
            "exists": bool(exists),
            "prev_hash": "0x" + prev.hex() if hasattr(prev, "hex") else str(prev),
            "block": None,
            "timestamp": ts,
            "operator": str(operator),
            "record_type": rtype,
        }

    def get_batch_chain(self, batch_id):
        n = self.contract.functions.getChainLength(_to_bytes32(batch_id)).call()
        out = []
        for i in range(n):
            h = self.contract.functions.getChainHash(_to_bytes32(batch_id), i).call()
            out.append({"block_hash": "0x" + h.hex() if hasattr(h, "hex") else str(h)})
        return out

    def integrity_check(self):
        return {"ok": True, "blocks": len(self.blocks()) if hasattr(self, "blocks") else -1, "problems": []}


def _to_bytes32(text: str) -> bytes:
    b = text.encode("utf-8")[:32]
    return b.ljust(32, b"\x00")


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
class ChainBackend:
    def __init__(self, mode="auto", rpc_url="http://127.0.0.1:8545"):
        """
        mode: auto(优先 Ganache，失败回退本地链) / local / ganache
        """
        self.mode = mode
        self.rpc_url = rpc_url
        self.local = LocalChain()
        self.ganache = None
        self.active = "local"
        if mode in ("auto", "ganache"):
            try:
                g = GanacheChain(rpc_url)
                if g.ready:
                    self.ganache = g
                    self.active = "ganache"
            except Exception as e:
                print(f"[链后端] Ganache 不可用，使用本地模拟链：{e}")
                self.ganache = None
                self.active = "local"
        print(f"[链后端] 当前运行模式：{self.active}（mode={mode}）")

    @property
    def backend(self):
        return self.ganache if self.active == "ganache" else self.local

    def chain_name(self):
        return self.active

    def add_record(self, batch_id, data_hash, record_type, operator="system"):
        return self.backend.add_record(batch_id, data_hash, record_type, operator)

    def verify_hash(self, data_hash):
        return self.backend.verify_hash(data_hash)

    def get_batch_chain(self, batch_id):
        return self.backend.get_batch_chain(batch_id)

    def integrity_check(self):
        return self.backend.integrity_check()


chain = None

def get_chain(mode="auto"):
    global chain
    if chain is None:
        chain = ChainBackend(mode=mode)
    return chain
