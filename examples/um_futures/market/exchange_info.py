#!/usr/bin/env python
import logging
from binance.um_futures import UMFutures
from binance.lib.utils import config_logging

config_logging(logging, logging.DEBUG)

def get_decimal_places(tick_size):
    tick_str = str(float(tick_size))
    if '.' in tick_str:
        return len(tick_str.split('.')[-1].rstrip('0'))
    return 0

client = UMFutures()
temp_exchange_info = client.exchange_info()['symbols']
symbol_info = {}
for item in temp_exchange_info:
    symbol_info[item['symbol']] = {
        'tick_size': get_decimal_places(item['filters'][0]['tickSize']),
        'min_qty': item['filters'][0]['minQty'],
        'max_qty': item['filters'][0]['maxQty'],
        'min_notional': item['filters'][0]['minNotional'],
        'max_notional': item['filters'][0]['maxNotional'],
    }


print("====================")
print(symbol_info["BTCUSDT"])
