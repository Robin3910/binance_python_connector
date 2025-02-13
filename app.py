# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from binance.um_futures import UMFutures as Client
import threading
import time
import requests
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import RotatingFileHandler
from binance.um_futures import UMFutures as Client
from binance.error import ClientError
from config import BINANCE_CONFIG, WX_CONFIG
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import secrets
from functools import wraps

app = Flask(__name__)

# 配置信息
WX_TOKEN = WX_CONFIG['token']

ip_white_list = BINANCE_CONFIG['ip_white_list']

# 添加 Flask secret key
app.secret_key = secrets.token_hex(16)

client = Client(
    BINANCE_CONFIG['key'], 
    BINANCE_CONFIG['secret'], 
    base_url=BINANCE_CONFIG['base_url']
)


def prefix_symbol(s: str) -> str:
    # BINANCE:BTCUSDT.P -> BTC-USDT-SWAP
    # 首先处理冒号，如果存在则取后面的部分
    if ':' in s:
        s = s.split(':')[1]
    
    # 检查字符串是否以".P"结尾并移除
    if s.endswith('.P'):
        s = s[:-2]
    
    return s

def send_wx_notification(title, message):
    """
    发送微信通知
    
    Args:
        title: 通知标题
        message: 通知内容
    """
    try:
        mydata = {
            'text': title,
            'desp': message
        }
        requests.post(f'https://wx.xtuis.cn/{WX_TOKEN}.send', data=mydata)
        logger.info('发送微信消息成功')
    except Exception as e:
        logger.error(f'发送微信消息失败: {str(e)}')

def get_decimal_places(tick_size):
    tick_str = str(float(tick_size))
    if '.' in tick_str:
        return len(tick_str.split('.')[-1].rstrip('0'))
    return 0

# 配置日志
def setup_logger():
    logger = logging.getLogger('grid_trader')
    logger.setLevel(logging.INFO)
    
    # 创建 rotating file handler，最大文件大小为 10MB，保留 5 个备份文件
    handler = RotatingFileHandler('grid_trader.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger

logger = setup_logger()

# 获取币种的精度
try:
    exchange_info = client.exchange_info()['symbols']
    symbol_tick_size = {}
    for item in exchange_info:
        symbol_tick_size[item['symbol']] = {
            'tick_size': get_decimal_places(item['filters'][0]['tickSize']),
            'min_qty': get_decimal_places(item['filters'][1]['minQty']),
        }
except ClientError as error:
    send_wx_notification(f'获取币种精度失败', f'获取币种精度失败，错误: {error}')
    logger.error(
        "Found error. status: {}, error code: {}, error message: {}".format(
            error.status_code, error.error_code, error.error_message
        )
    )

# 创建全局字典来存储不同币种的交易信息
trading_pairs = {}
# 请求参数
# {
#     "symbol": "BTCUSDT",
#     "entry_price_percent": 0.01,
#     "entry_usdt": 300,
#     "exit_price_percent": 0.01,
#     "open_price": 10000,
# }
@app.route('/message', methods=['POST'])
def handle_message():
    try:
        data = request.get_json()
        symbol = data['symbol']
        entry_price_percent = float(data['entry_price_percent'])
        entry_usdt = float(data['entry_usdt'])
        exit_price_percent = float(data['exit_price_percent'])
        open_price = float(data['open_price'])
        logger.info(f'收到 {symbol} 的新交易参数请求: {json.dumps(data, ensure_ascii=False)}')

        trading_pairs[symbol] = {
            'entry_price_percent': entry_price_percent,
            'entry_usdt': entry_usdt,
            'exit_price_percent': exit_price_percent,
            'open_price': open_price,
        }

        # 判断是否有持仓
        pos_response = client.position_risk(symbol)
        position_qty = 0
        if pos_response and len(pos_response) > 0:
            position_qty = float(pos_response[0]['positionAmt'])
            entry_price = float(pos_response[0]['entryPrice'])
        if position_qty != 0:
            # 判断一下上一次的出场单是否已经成交
            if trading_pairs[symbol]['exit_order_id'] is not None:
                order_response = client.get_order(symbol, trading_pairs[symbol]['exit_order_id'])
                if order_response['status'] == 'FILLED':
                    # 已经成交的话应该就没仓位了
                    logger.info(f'{symbol} | 上一次的出场单已经成交')
                else:
                    logger.warning(f'{symbol} | 上一次的出场单未成交,撤掉上一次的出场单')
                    # 删除上一次的出场单
                    client.cancel_order(symbol, trading_pairs[symbol]['exit_order_id'])

                    # 挂个新的出场单
                    order_response = client.new_order(
                        symbol=symbol,
                        side="SELL",
                        type="LIMIT",
                        quantity=position_qty,
                        timeInForce="GTC",
                        price=round(open_price * (1-exit_price_percent), symbol_tick_size[symbol]['tick_size'])
                    )
                    logger.info(order_response)
                    if order_response['orderId'] is not None:
                        trading_pairs[symbol]['exit_order_id'] = order_response['orderId']
                        logger.info(f'{symbol} | 出场单已创建，ID: {trading_pairs[symbol]["exit_order_id"]}')
                        send_wx_notification(f'{symbol} | 出场单已创建', f'出场单已创建，ID: {trading_pairs[symbol]["exit_order_id"]}')
                    else:
                        logger.error(f'{symbol} | 出场单创建失败，响应: {order_response}')
                        send_wx_notification(f'{symbol} | 出场单创建失败', f'出场单创建失败，响应: {order_response}')

        # 判断之前的限价单是否已经成交，如果没成交，挂上一个限价单
        if trading_pairs[symbol]['entry_order_id'] is not None:
            order_response = client.get_order(symbol, trading_pairs[symbol]['entry_order_id'])
            if order_response['status'] == 'FILLED':
                logger.info(f'{symbol} | 入场单已经成交')
            else:
                logger.warning(f'{symbol} | 入场单未成交,撤掉入场单')
                client.cancel_order(symbol, trading_pairs[symbol]['entry_order_id'])

                # 挂上一个新的入场单
                order_response = client.new_order(
                    symbol=symbol,
                    side="BUY",
                    type="LIMIT",
                    quantity=position_qty,
                    timeInForce="GTC",
                    price=round(open_price * (1-entry_price_percent), symbol_tick_size[symbol]['tick_size'])
                )
                logger.info(order_response)
                if order_response['orderId'] is not None:
                    trading_pairs[symbol]['entry_order_id'] = order_response['orderId']
                    logger.info(f'{symbol} | 入场单已创建，ID: {trading_pairs[symbol]["entry_order_id"]}')
                    send_wx_notification(f'{symbol} | 入场单已创建', f'入场单已创建，ID: {trading_pairs[symbol]["entry_order_id"]}')
                else:
                    logger.error(f'{symbol} | 入场单创建失败，响应: {order_response}')
                    send_wx_notification(f'{symbol} | 入场单创建失败', f'入场单创建失败，响应: {order_response}')

        logger.info(f'{symbol} 交易参数设置成功')
        return jsonify({"status": "success", "message": f"{symbol} 交易参数设置成功"})
    except Exception as e:
        logger.error(f'设置交易参数失败: {str(e)}')
        return jsonify({"status": "error", "message": str(e)})

def send_wx_message():
    """发送微信消息"""
    while True:
        try:
            # 获取当前时间
            current_hour = datetime.now().hour
            # 获取当前分钟
            current_minute = datetime.now().minute
            # 只在整点0分时发送消息
            if current_minute != 0:
                time.sleep(30)  # 如果不是整点,休眠1分钟后继续检查
                continue
            # 只在指定时间点发送消息
            if current_hour in [0, 4, 8, 12, 16, 20]:
                # 为每个交易对生成状态信息
                status_messages = []
                balance = 0
                # 从Binance获取实时数据
                try:
                    response = client.balance(recvWindow=6000)
                    for item in response:
                        if item['asset'] == 'USDT':
                            balance = item['balance']
                            break
                except ClientError as error:
                    logger.error(
                        "Found error. status: {}, error code: {}, error message: {}".format(
                            error.status_code, error.error_code, error.error_message
                        )
                    )
                for symbol, trader in trading_pairs.items():
                    if trader.is_monitoring:
                        current_price = client.mark_price(symbol)['markPrice']
                        status_messages.append(f"""
                                            {symbol} 交易状态:
                                            当前币种价格: {current_price}
                                            当前止损价格: {trader.stop_loss_price}
                                            处于第几个网格: 第{trader.current_grid + 1}网格
                                            当前网格大小: {trader.grids[trader.current_grid]['size']}
                                            当前持仓数量: {trader.position_qty}
                                            当前持仓方向: {trader.side}
                                            当前网格边界: {trader.grids[trader.current_grid]['lower']} - {trader.grids[trader.current_grid]['upper']}
                                            """)
                    else:
                        current_price = 0
                    
                
                message = "\n".join(status_messages)+f"\n当前账户余额: {balance}\n" + f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                mydata = {
                    'text': '交易状态定时报告',
                    'desp': message
                }
                requests.post(f'https://wx.xtuis.cn/{WX_TOKEN}.send', data=mydata)
                logger.info('发送微信消息成功')
            
            # 休眠到下一个小时
            next_hour = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            sleep_seconds = (next_hour - datetime.now()).total_seconds()
            time.sleep(sleep_seconds)
            
        except Exception as e:
            logger.error(f'发送微信消息失败: {str(e)}')
            time.sleep(60)  # 发生错误时等待1分钟后重试



@app.before_request
def before_req():
    # 排除登录路由和静态文件
    if request.path == '/login' or request.path == '/' or request.path.startswith('/static'):
        return
        
    # 只对 POST 请求进行 JSON 和 IP 检查
    if request.method == 'POST':
        # 检查 Content-Type
        if not request.is_json:
            return jsonify({'error': 'Content-Type 必须是 application/json'}), 415
            
        if request.json is None:
            return jsonify({'error': '请求体不能为空'}), 400
            
        if request.remote_addr not in ip_white_list:
            logger.info(f'ipWhiteList: {ip_white_list}')
            logger.info(f'ip is not in ipWhiteList: {request.remote_addr}')
            return jsonify({'error': 'ip is not in ipWhiteList'}), 403

# 添加登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 登录路由
@app.route('/', methods=['GET'])
@app.route('/login', methods=['GET', "POST"])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'leledahuanxi123':
            session['logged_in'] = True
            return redirect(url_for('config'))
        return render_template('login.html', error='密码错误')
    return render_template('login.html')

# 配置页面路由
@app.route('/config', methods=['GET'])
@login_required
def config():
    return render_template('config.html')

# 更新配置接口
@app.route('/update_config', methods=['POST'])
@login_required
def update_config():
    try:
        data = request.get_json()
        api_key = data.get('api_key')
        api_secret = data.get('api_secret')
        environment = data.get('environment')
        
        # 更新 client
        global client
        base_url = 'https://fapi.binance.com' if environment == 'PRD' else 'https://testnet.binancefuture.com'
        client = Client(api_key, api_secret, base_url=base_url)
        
        # 测试连接
        client.account()
        
        return jsonify({"status": "success", "message": "配置更新成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/reset_trading', methods=['GET'])
@login_required
def reset_trading():
    try:
        global trading_pairs
        trading_pairs = {}
        logger.info('所有交易参数已重置')
        return jsonify({"status": "success", "message": "所有交易参数已重置"})
    except Exception as e:
        logger.error(f'重置交易参数失败: {str(e)}')
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':

    # 启动Flask服务
    app.run(host='0.0.0.0', port=80)
