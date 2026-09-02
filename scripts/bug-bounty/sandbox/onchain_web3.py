#!/usr/bin/env python3
"""Open-Source Onchain Adapter — local wallet + Uniswap V3 swaps via web3.py.

No Coinbase. No CDP. No API keys. Pure open-source onchain execution.

Architecture:
  - Local Ethereum wallet (generated or loaded from private key)
  - Base Sepolia testnet (public RPC)
  - Uniswap V3 router for token swaps
  - Pyth oracle or Uniswap TWAP for price feeds
  - Native ETH for gas, tokens for trading

Usage (harness):
    adapter = Web3Onchain(private_key="0x...", network="base-sepolia")
    adapter.initialize()
    adapter.swap(from_token="USDC", to_token="WETH", amount=100)

Wallet setup:
    # Generate a new wallet:
    python3 -c "from eth_account import Account; a=Account.create(); print(a.key.hex())"
    # Fund with Base Sepolia ETH from faucet: https://www.alchemy.com/faucets/base-sepolia
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("opentrader.web3onchain")

# ── Uniswap V3 Router (Base Sepolia) ──
UNISWAP_V3_ROUTER = "0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4"  # Base Sepolia

# ── Token addresses (Base Sepolia) ──
TOKENS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "USDT": "0x48C6347D02277af0FCcDbB7D97CB3C21Be938F7b",
    "DAI": "0x7151C1A1ECF0AcF8D2b3c49b27027A27FA1C4Ab4",
    "WBTC": "0x87eEE96D50F761d85BA9828B9A2A5664B6f8227a",
}

# ── Uniswap V3 Router ABI (swapExactInputSingle) ──
ROUTER_ABI = json.loads("""
[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct IV3SwapRouter.ExactInputSingleParams","name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}]
""")


class Web3Onchain:
    """Open-source onchain adapter — web3 wallet + Uniswap V3 on Base Sepolia."""

    def __init__(self, private_key: str = None, network: str = "base-sepolia",
                 rpc_url: str = None):
        self._private_key = private_key
        self._network = network
        self._rpc_url = rpc_url
        self._w3 = None
        self._account = None
        self._initialized = False

        # Default RPC URLs
        self._rpc_defaults = {
            "base-sepolia": "https://sepolia.base.org",
            "base-mainnet": "https://mainnet.base.org",
        }

    def initialize(self) -> bool:
        from web3 import Web3
        from eth_account import Account

        rpc = self._rpc_url or self._rpc_defaults.get(self._network, "https://sepolia.base.org")
        self._w3 = Web3(Web3.HTTPProvider(rpc))

        if not self._private_key:
            # Generate new wallet or load from env
            self._private_key = os.getenv("ONCHAIN_PRIVATE_KEY")
            if not self._private_key:
                acct = Account.create()
                self._private_key = acct.key.hex()
                logger.warning(
                    "No private key — generated new wallet: %s...%s",
                    acct.address[:10], acct.address[-6:]
                )
                logger.info(
                    "Save this key: ONCHAIN_PRIVATE_KEY=%s", self._private_key
                )

        self._account = Account.from_key(self._private_key)
        balance = self._w3.eth.get_balance(self._account.address)
        balance_eth = self._w3.from_wei(balance, "ether")

        self._initialized = True
        logger.info(
            "Web3 wallet ready — network=%s address=%s...%s balance=%s ETH",
            self._network,
            self._account.address[:10], self._account.address[-6:],
            round(float(balance_eth), 6),
        )

        if float(balance_eth) < 0.001:
            logger.warning(
                "Low ETH balance — get testnet ETH from faucet: "
                "https://www.alchemy.com/faucets/base-sepolia"
            )

        return True

    @property
    def ready(self) -> bool:
        return self._initialized and self._w3 is not None and self._account is not None

    @property
    def address(self) -> str:
        return self._account.address if self._account else ""

    def get_balance(self, token: str = "native") -> dict:
        """Get balance of native ETH or token."""
        if not self._w3 or not self._account:
            return {}
        if token.lower() == "native":
            bal = self._w3.eth.get_balance(self._account.address)
            return {"balance": float(self._w3.from_wei(bal, "ether")), "symbol": "ETH"}
        addr = TOKENS.get(token.upper())
        if not addr:
            return {"error": f"unknown token: {token}"}
        erc20 = self._w3.eth.contract(
            address=addr,
            abi=[{"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
                  "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
                  "type": "function"}]
        )
        bal = erc20.functions.balanceOf(self._account.address).call()
        return {"balance": bal, "symbol": token, "raw": bal}

    def swap(self, from_token: str, to_token: str, amount: float,
             slippage: float = 0.01) -> Optional[dict]:
        """Swap tokens via Uniswap V3 on Base Sepolia.

        Args:
            from_token: Token symbol to sell ("USDC", "WETH", "native" for ETH)
            to_token: Token symbol to buy
            amount: Amount of from_token to sell
            slippage: Slippage tolerance (0.01 = 1%)
        """
        if not self._w3 or not self._account:
            return None

        from_addr = TOKENS.get(from_token.upper())
        to_addr = TOKENS.get(to_token.upper())

        if not from_addr and from_token.upper() != "NATIVE":
            return {"error": f"unknown from_token: {from_token}"}
        if not to_addr and to_token.upper() != "NATIVE":
            return {"error": f"unknown to_token: {to_token}"}

        try:
            router = self._w3.eth.contract(
                address=UNISWAP_V3_ROUTER,
                abi=ROUTER_ABI,
            )

            # Determine amount in wei
            if from_token.upper() == "NATIVE":
                # Wrapping ETH → WETH
                amount_wei = self._w3.to_wei(amount, "ether")
                from_addr_input = TOKENS["WETH"]  # Actually use WETH
                value_eth = amount_wei
            else:
                amount_wei = amount  # raw token amount
                from_addr_input = from_addr
                value_eth = 0

            # Build swap params
            params = {
                "tokenIn": from_addr_input,
                "tokenOut": to_addr,
                "fee": 3000,  # 0.3% Uniswap pool
                "recipient": self._account.address,
                "amountIn": amount_wei,
                "amountOutMinimum": 0,  # Could be tightened with a quote
                "sqrtPriceLimitX96": 0,
            }

            tx = router.functions.exactInputSingle(params).build_transaction({
                "from": self._account.address,
                "value": value_eth,
                "gas": 300000,
                "gasPrice": self._w3.eth.gas_price,
                "nonce": self._w3.eth.get_transaction_count(self._account.address),
            })

            signed = self._w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return {
                "tx_hash": tx_hash.hex(),
                "status": "success" if receipt.status == 1 else "failed",
                "gas_used": receipt.gasUsed,
                "block": receipt.blockNumber,
            }
        except Exception as e:
            logger.error("Swap failed: %s", e)
            return {"error": str(e), "status": "failed"}

    def get_price(self, symbol: str) -> Optional[float]:
        """Get approximate price from Uniswap pool (spot quote)."""
        if not self._w3:
            return None
        return None  # placeholder — full TWAP needs pool contract

    def estimate_gas(self) -> dict:
        """Estimate gas costs for a Uniswap swap."""
        if not self._w3:
            return {"error": "not connected"}
        try:
            gas_price = self._w3.eth.gas_price
            gas_gwei = float(self._w3.from_wei(gas_price, 'gwei'))
            # Typical Uniswap V3 swap: ~150k-300k gas
            gas_cost_eth = float(self._w3.from_wei(gas_price * 200000, 'ether'))
            eth_price = 3000  # rough estimate
            return {
                "gas_price_gwei": round(gas_gwei, 1),
                "estimated_gas_units": 200000,
                "estimated_cost_eth": round(gas_cost_eth, 6),
                "estimated_cost_usd": round(gas_cost_eth * eth_price, 2),
                "network": self._network,
            }
        except Exception as e:
            return {"error": str(e)}

    def get_swap_quote(self, from_token: str, to_token: str, amount: float) -> dict:
        """Get a quote for a swap without executing."""
        if not self._w3:
            return {"error": "not connected"}
        from_addr = TOKENS.get(from_token.upper())
        to_addr = TOKENS.get(to_token.upper())
        if not from_addr or not to_addr:
            return {"error": f"unknown token: {from_token} or {to_token}"}
        gas = self.estimate_gas()
        return {
            "from": from_token, "to": to_token,
            "amount": amount,
            "estimated_cost_usd": gas.get("estimated_cost_usd", 0),
            "network": self._network,
        }
