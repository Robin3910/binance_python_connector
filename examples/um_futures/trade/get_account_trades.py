#!/usr/bin/env python
import logging
from binance.um_futures import UMFutures
from binance.lib.utils import config_logging
from binance.error import ClientError

config_logging(logging, logging.DEBUG)

key = "6953af36dcec691ee0cb266cf60d13e58bcc3f9c8f9d71b8b899090e649e3898"
secret = "2e9d0e67d0585312bbefc7aa7e4dcbdb1d2991b8b7665a76c4c11b022bc88f91"
test_url = "https://testnet.binancefuture.com"

client = UMFutures(key=key, secret=secret, **{'base_url': test_url})

def get_decimal_places(tick_size):
    tick_str = str(float(tick_size))
    if '.' in tick_str:
        return len(tick_str.split('.')[-1].rstrip('0'))
    return 0

# 获取币种的精度
exchange_info = client.exchange_info()['symbols']
symbol_tick_size = {}
for item in exchange_info:
    symbol_tick_size[item['symbol']] = get_decimal_places(item['filters'][0]['tickSize'])

print(symbol_tick_size["BTCUSDT"])