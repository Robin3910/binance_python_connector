#!/usr/bin/env python
import logging
from binance.um_futures import UMFutures
from binance.lib.utils import config_logging
from binance.error import ClientError

config_logging(logging, logging.DEBUG)

key = "6953af36dcec691ee0cb266cf60d13e58bcc3f9c8f9d71b8b899090e649e3898"
secret = "2e9d0e67d0585312bbefc7aa7e4dcbdb1d2991b8b7665a76c4c11b022bc88f91"
test_url = "https://testnet.binancefuture.com"

um_futures_client = UMFutures(key=key, secret=secret, **{'base_url': test_url})

try:
    response = um_futures_client.new_order(
        symbol="BTCUSDT",
        side="SELL",
        positionSide="LONG",
        type="LIMIT",
        quantity=0.01,
        timeInForce="GTC",
        price=82000,
    )
    logging.info(response)
except ClientError as error:
    logging.error(
        "Found error. status: {}, error code: {}, error message: {}".format(
            error.status_code, error.error_code, error.error_message
        )
    )
