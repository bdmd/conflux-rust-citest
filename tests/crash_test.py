#!/usr/bin/env python3
import datetime

from eth_utils import decode_hex
from rlp.sedes import Binary, BigEndianInt

from conflux import utils
from conflux.utils import encode_hex, bytes_to_int, priv_to_addr, parse_as_int
from conflux.rpc import RpcClient
from test_framework.blocktools import create_block, create_transaction
from test_framework.test_framework import ConfluxTestFramework
from test_framework.mininode import *
from test_framework.util import *


class CrashTest(ConfluxTestFramework):
    def set_test_params(self):
        self.num_nodes = 8

    def setup_network(self):
        self.add_nodes(self.num_nodes)
        bootnode = self.nodes[0]
        extra_args0 = ["--enable-discovery", "true", "--node-table-timeout-s", "1", "--node-table-promotion-timeout-s", "1"]
        self.start_node(0, extra_args = extra_args0)
        bootnode_id = "cfxnode://{}@{}:{}".format(bootnode.key[2:], bootnode.ip, bootnode.port)
        self.node_extra_args = ["--bootnodes", bootnode_id, "--enable-discovery", "true", "--node-table-timeout-s", "1", "--node-table-promotion-timeout-s", "1"]
        for i in range(1, self.num_nodes):
            self.start_node(i, extra_args=self.node_extra_args)
        for i in range(self.num_nodes):
            # Make sure the graph is connected even after we stop node 0.
            wait_until(lambda: len(self.nodes[i].test_getPeerInfo()) >= 4)

    def run_test(self):
        block_number = 10

        for i in range(1, block_number):
            chosen_peer = random.randint(0, self.num_nodes - 1)
            block_hash = self.nodes[chosen_peer].test_generateEmptyBlocks(1)
            self.log.info("generate block %s", block_hash)
        wait_for_block_count(self.nodes[0], block_number, timeout=30)
        sync_blocks(self.nodes, timeout=30)
        self.log.info("generated blocks received by all")

        self.stop_node(0, kill=True)
        self.log.info("node 0 stopped")
        block_hash = self.nodes[-1].test_generateEmptyBlocks(1)
        self.log.info("generate block %s", block_hash)
        wait_for_block_count(self.nodes[1], block_number + 1)
        sync_blocks(self.nodes[1:], timeout=30)
        self.log.info("blocks sync success among running nodes")
        self.start_node(0)
        sync_blocks(self.nodes, timeout=30)
        self.log.info("Pass 1")

        for i in range(1, self.num_nodes):
            self.stop_node(i, kill=True)
        genesis = self.nodes[0].cfx_getBlockByEpochNumber("0x0", False)["hash"]
        self.nodes[0].add_p2p_connection(P2PInterface(genesis))
        self.nodes[0].p2p.wait_for_status()
        client = RpcClient(self.nodes[0])
        gas_price = 1
        value = 1
        receiver_sk, _ = ec_random_keys()
        sender_key = default_config["GENESIS_PRI_KEY"]
        tx = create_transaction(pri_key=sender_key, receiver=priv_to_addr(receiver_sk), value=value, nonce=0,
                                gas_price=gas_price)
        self.nodes[0].p2p.send_protocol_msg(Transactions(transactions=[tx]))
        self.log.debug("New tx %s: %s send value %d to %s", encode_hex(tx.hash), eth_utils.encode_hex(priv_to_addr(sender_key))[-4:],
                       value, eth_utils.encode_hex(priv_to_addr(receiver_sk))[-4:])
        def check_packed():
            client.generate_block(1)
            return checktx(self.nodes[0], tx.hash_hex())
        wait_until(lambda: check_packed())
        sender_addr = eth_utils.encode_hex(priv_to_addr(sender_key))
        receiver_addr = eth_utils.encode_hex(priv_to_addr(receiver_sk))
        sender_balance = default_config["TOTAL_COIN"] - value - gas_price * 21000
        # Generate 2 * CACHE_INDEX_STRIDE to start evicting anticone cache
        self.nodes[0].test_generateEmptyBlocks(1000)
        self.nodes[0].test_generateEmptyBlocks(1000)
        assert_equal(client.get_balance(sender_addr), sender_balance)
        assert_equal(client.get_balance(receiver_addr), value)
        time.sleep(1)
        self.stop_node(0)
        self.start_node(0)
        self.log.info("Wait for node 0 to recover from crash")
        wait_until(lambda: client.get_balance(sender_addr) == sender_balance)
        wait_until(lambda: client.get_balance(receiver_addr) == value)
        self.log.info("Pass 2")


if __name__ == "__main__":
    CrashTest().main()
