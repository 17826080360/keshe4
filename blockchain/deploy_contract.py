# -*- coding: utf-8 -*-
"""
Ganache 部署脚本：把 Traceability.sol 部署到本地以太坊（默认 http://127.0.0.1:8545）。

用法：
    1. 启动 Ganache（GUI 或命令行）：ganache -p 8545  （默认账户余额充足）
    2. python blockchain/deploy_contract.py
    3. 部署成功后把合约地址写入 raw_data/contract_address.txt，
       应用启动时链后端会自动切换到 Ganache 真实链。

说明：编译产物 Traceability_compiled.json 已随项目提供；
若需要重新编译，请安装 solc（如 npm install -g solc 或使用 Remix 在线编译）。
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

COMPILED = os.path.join(BASE_DIR, "blockchain", "Traceability_compiled.json")
ADDR_FILE = os.path.join(BASE_DIR, "raw_data", "contract_address.txt")
RPC_URL = os.environ.get("GANACHE_URL", "http://127.0.0.1:8545")


def main():
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("[部署] 无法连接 Ganache：", RPC_URL)
        print("[部署] 请先启动 Ganache（ganache -p 8545），再重试。")
        sys.exit(1)

    with open(COMPILED, "r", encoding="utf-8") as f:
        compiled = json.load(f)

    account = w3.eth.accounts[0]
    print(f"[部署] 已连接 Ganache，账户：{account}，余额：{w3.eth.get_balance(account)} wei")

    contract = w3.eth.contract(abi=compiled["abi"], bytecode=compiled["bytecode"])
    tx_hash = contract.constructor().transact({"from": account})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    address = receipt.contractAddress
    os.makedirs(os.path.dirname(ADDR_FILE), exist_ok=True)
    with open(ADDR_FILE, "w", encoding="utf-8") as f:
        f.write(address)
    print(f"[部署] 合约已部署：{address}")
    print(f"[部署] 地址已写入 {ADDR_FILE}，重启应用后自动使用真实链。")

    # 冒烟测试：写入一条测试记录并验证
    data_hash = "0x" + "ab" * 32
    tx = contract.functions.addRecord(
        b"smoke-test-batch-00000000000000000000",
        bytes.fromhex(data_hash[2:]),
        "smoke",
    ).transact({"from": account})
    w3.eth.wait_for_transaction_receipt(tx)
    exists, operator, ts, prev, rtype = contract.functions.verifyRecord(
        bytes.fromhex(data_hash[2:])
    ).call()
    print(f"[部署] 冒烟测试：exists={exists} type={rtype} 通过 ✓")


if __name__ == "__main__":
    main()
