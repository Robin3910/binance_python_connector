# -*- coding: utf-8 -*-

from binance.cm_futures import CMFutures as Client

key = ""
secret = ""
BASE_URL = "https://fapi.binance.com"
TEST_BASE_URL = "https://testnet.binancefuture.com"

client = Client(key, secret, base_url=TEST_BASE_URL)
