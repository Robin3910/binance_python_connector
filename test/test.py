def prefix_symbol(s: str, type: str = "um") -> str:
    # BINANCE:BTCUSDT.P -> BTC-USDT-SWAP
    # 首先处理冒号，如果存在则取后面的部分
    if ":" in s:
        s = s.split(":")[1]

    # 检查字符串是否以".P"结尾并移除
    if s.endswith(".P"):
        s = s[:-2]

    if type == "cm":
        s = s.replace("USDT", "USD")
        s += "_PERP"

    return s



print(prefix_symbol("BTCUSDT.P", "cm"))
