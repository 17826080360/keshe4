// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title Traceability 农产品溯源合约
 * @dev 记录数据指纹（内容哈希），按批次构建哈希链，实现防篡改。
 *      链上只存哈希与元信息，明文数据存业务数据库 —— 分层存储。
 *      上链 = 存证；验证 = 比对数据库内容重算哈希是否与链上一致。
 */
contract Traceability {
    struct ChainRecord {
        bytes32 dataHash;     // 数据指纹 sha256(规范化内容)
        bytes32 prevHash;     // 同批次上一条记录的哈希（哈希链指针）
        address operator;     // 录入人链上地址
        uint256 timestamp;    // 上链时间
        string  recordType;   // 记录类型：farming/process/logistics/list/sale...
    }

    // dataHash => 链上记录
    mapping(bytes32 => ChainRecord) public records;
    // batchId(bytes32) => 按序存储的哈希链
    mapping(bytes32 => bytes32[]) public batchChain;
    // batchId => 已上链条数
    mapping(bytes32 => uint256) public chainLength;

    event RecordAdded(bytes32 indexed batchId, bytes32 recordHash, string recordType, uint256 timestamp);

    /** 上链一条记录：把数据指纹追加到指定批次哈希链末尾 */
    function addRecord(
        bytes32 batchId,
        bytes32 dataHash,
        string calldata recordType
    ) external returns (bytes32) {
        require(dataHash != bytes32(0), "dataHash cannot be zero");
        require(records[dataHash].operator == address(0), "record already exists");

        bytes32 prev = batchChain[batchId].length > 0
            ? batchChain[batchId][batchChain[batchId].length - 1]
            : bytes32(0);

        records[dataHash] = ChainRecord(dataHash, prev, msg.sender, block.timestamp, recordType);
        batchChain[batchId].push(dataHash);
        chainLength[batchId] = batchChain[batchId].length;

        emit RecordAdded(batchId, dataHash, recordType, block.timestamp);
        return dataHash;
    }

    /** 验证单条记录是否上链，返回存证信息 */
    function verifyRecord(bytes32 dataHash)
        external view
        returns (bool exists, address operator, uint256 timestamp, bytes32 prevHash, string memory recordType)
    {
        ChainRecord memory r = records[dataHash];
        if (r.operator == address(0)) {
            return (false, address(0), 0, bytes32(0), "");
        }
        return (true, r.operator, r.timestamp, r.prevHash, r.recordType);
    }

    /** 获取某批次哈希链上指定位置的哈希 */
    function getChainHash(bytes32 batchId, uint256 index) external view returns (bytes32) {
        require(index < batchChain[batchId].length, "index out of range");
        return batchChain[batchId][index];
    }

    /** 获取某批次上链条数 */
    function getChainLength(bytes32 batchId) external view returns (uint256) {
        return batchChain[batchId].length;
    }
}
