# Binance API配置
env = 'test'
BINANCE_CONFIG = {
    'key': '6953af36dcec691ee0cb266cf60d13e58bcc3f9c8f9d71b8b899090e649e3898',
    'secret': '2e9d0e67d0585312bbefc7aa7e4dcbdb1d2991b8b7665a76c4c11b022bc88f91',
    'base_url': 'https://fapi.binance.com' if env == 'prod' else 'https://testnet.binancefuture.com',
    'ip_white_list': ['52.89.214.238', '34.212.75.30', '54.218.53.128', '52.32.178.7', '127.0.0.1']
}
BINANCE_CM_CONFIG={
    'key': '8a75263f1d18ef611dd4e920215cb71d47474f5e1168fab6023b3ba929fc7b5e',
    'secret': 'de82f4cce06f0aafc520ece0786b6f389edef4d602c19aef33ab08fd8c7f4a1b',
    'base_url': 'https://dapi.binance.com' if env == 'prod' else 'https://testnet.binancefuture.com',
    'ip_white_list': ['52.89.214.238', '34.212.75.30', '54.218.53.128', '52.32.178.7', '127.0.0.1']
}
# 微信通知配置
WX_CONFIG = {
    'token': '8nEhpKFjhU9uKaDDnfDseWy1P'
} 