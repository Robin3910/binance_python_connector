# Binance API配置
env = 'test'
BINANCE_CONFIG = {
    'key': '6953af36dcec691ee0cb266cf60d13e58bcc3f9c8f9d71b8b899090e649e3898',
    'secret': '2e9d0e67d0585312bbefc7aa7e4dcbdb1d2991b8b7665a76c4c11b022bc88f91',
    'base_url': 'https://fapi.binance.com' if env == 'prod' else 'https://testnet.binancefuture.com'
}

# 微信通知配置
WX_CONFIG = {
    'token': '8nEhpKFjhU9uKaDDnfDseWy1P'
} 