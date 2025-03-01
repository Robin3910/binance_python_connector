# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import time
import requests
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import RotatingFileHandler
from binance.um_futures import UMFutures as Client
from binance.error import ClientError
from config import BINANCE_CONFIG, WX_CONFIG
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
    if exchange_info is None:
        raise Exception('获取币种精度失败')
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

# 统一设置持仓模式
try:
    change_position_mode_response = client.change_position_mode(dualSidePosition=True)
    if change_position_mode_response['code'] == 200 or change_position_mode_response['code'] == -4059:
        logger.info(f'设置持仓模式成功: {change_position_mode_response}|是否为单向持仓: {change_position_mode_response["dualSidePosition"] != True}')
    else:
        send_wx_notification(f'设置持仓模式失败', f'设置持仓模式失败，错误: {change_position_mode_response}')
        logger.error(f'设置持仓模式失败，错误: {change_position_mode_response}')
except Exception as e:
    if e.error_code == -4059:
        logger.info(f'设置持仓模式成功')
    else:
        send_wx_notification(f'设置持仓模式失败', f'设置持仓模式失败，错误: {e}')
        logger.error(f'设置持仓模式失败，错误: {e}')

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

# 添加JSON文件操作函数
def load_trading_pairs():
    """从JSON文件加载交易对信息"""
    try:
        if os.path.exists('trading_pairs.json'):
            with open('trading_pairs.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f'加载trading_pairs.json失败: {str(e)}')
        return {}

def save_trading_pairs(trading_pairs):
    """保存交易对信息到JSON文件"""
    try:
        with open('trading_pairs.json', 'w', encoding='utf-8') as f:
            json.dump(trading_pairs, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f'保存trading_pairs.json失败: {str(e)}')

@app.route('/message', methods=['POST'])
def handle_message():
    try:
        # 从JSON文件加载现有的交易对信息
        global trading_pairs
        trading_pairs = load_trading_pairs()
        
        data = request.get_json()
        symbol = prefix_symbol(data['symbol'])
        entry_price_percent = float(data['entry_price_percent'])
        entry_usdt = float(data['entry_usdt'])
        exit_price_percent = float(data['exit_price_percent'])
        open_price = float(data['open_price'])
        logger.info(f'收到 {symbol} 的新交易参数请求: {json.dumps(data, ensure_ascii=False)}')

        if trading_pairs.get(symbol) is None:
            trading_pairs[symbol] = {
                'entry_price_percent': entry_price_percent,
                'entry_usdt': entry_usdt,
                'exit_price_percent': exit_price_percent,
                'open_price': open_price,
                'entry_order_id': None,
                'exit_order_id': None,
            }

        # 判断是否有持仓
        pos_response = client.get_position_risk(recvWindow=60000)
        
        position_qty = 0
        if pos_response and len(pos_response) > 0:
            for item in pos_response:
                if item['symbol'] == symbol:
                    position_qty = float(item['positionAmt'])
                    break
        if position_qty != 0:
            # 判断一下上一次的出场单是否已经成交
            if trading_pairs[symbol]['exit_order_id'] is not None:
                order_response = client.query_order(symbol, trading_pairs[symbol]['exit_order_id'])
                if order_response['status'] == 'FILLED' or order_response['status'] == 'CANCELED':
                    # 已经成交的话应该就没仓位了
                    logger.info(f"{symbol} | 上一次的出场单已经成交or已撤单, orderId: {trading_pairs[symbol]['exit_order_id']}")
                else:
                    logger.info(f"{symbol} | 上一次的出场单未成交,撤掉上一次的出场单")
                    # 删除上一次的出场单
                    cancel_response = client.cancel_order(symbol, trading_pairs[symbol]['exit_order_id'])
                    if cancel_response['status'] == 'CANCELED':
                        logger.info(f"{symbol} | 上一次的出场单已撤单")
                    else:
                        logger.error(f"{symbol} | 上一次的出场单撤单失败，响应: {cancel_response}")
                        send_wx_notification(f'{symbol} | 上一次的出场单撤单失败', f'上一次的出场单撤单失败，响应: {cancel_response}')

            # 挂个新的出场单
            order_response = client.new_order(
                symbol=symbol,
                side="SELL",
                type="LIMIT",
                positionSide="LONG",
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
                logger.info(f'{symbol} | 出场单创建失败，响应: {order_response}')
                send_wx_notification(f'{symbol} | 出场单创建失败', f'出场单创建失败，响应: {order_response}')

        # 判断之前的限价单是否已经成交，如果没成交，先撤单
        if trading_pairs[symbol]['entry_order_id'] is not None:
            order_response = client.query_order(symbol, trading_pairs[symbol]['entry_order_id'])
            if order_response['status'] == 'FILLED' or order_response['status'] == 'CANCELED':
                logger.info(f'{symbol} | 入场单已经成交or已撤单')
            else:
                logger.info(f'{symbol} | 入场单未成交,撤掉入场单')
                cancel_response = client.cancel_order(symbol, trading_pairs[symbol]['entry_order_id'])
                if cancel_response['status'] == 'CANCELED':
                    logger.info(f'{symbol} | 入场单已撤单')
                else:
                    logger.error(f'{symbol} | 入场单撤单失败，响应: {cancel_response}')
                    send_wx_notification(f'{symbol} | 入场单撤单失败', f'入场单撤单失败，响应: {cancel_response}')

        # 无论之前的单子是否成交，都需要挂上一个新的入场单
        entry_price = round(open_price * (1-entry_price_percent), symbol_tick_size[symbol]['tick_size'])
        qty = round(entry_usdt / entry_price, symbol_tick_size[symbol]['min_qty'])
        order_response = client.new_order(
            symbol=symbol,
            side="BUY",
            type="LIMIT",
            positionSide="LONG",
            quantity=qty,
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

        # 在处理完成后保存交易对信息
        save_trading_pairs(trading_pairs)
        
        logger.info(f'{symbol} 交易参数设置成功')
        return jsonify({"status": "success", "message": f"{symbol} 交易参数设置成功"})
    except Exception as e:
        logger.error(f'设置交易参数失败: {str(e)}')
        return jsonify({"status": "error", "message": str(e)})

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
            
        if request.path != '/update_config' and request.remote_addr not in ip_white_list:
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
        client = Client(api_key, api_secret, **{'base_url': base_url})
        
        # 测试连接
        account_response = client.account()
        logger.info(account_response)
        if account_response is None:
            raise Exception('连接失败')
        
        # 统一设置成单向持仓
        try:
            change_position_mode_response = client.change_position_mode(dualSidePosition=False)
            if change_position_mode_response['code'] == 200 or change_position_mode_response['code'] == -4059:
                # send_wx_notification(f'设置单向持仓成功', f'设置单向持仓成功: {change_position_mode_response}')
                logger.info(f'设置单向持仓成功: {change_position_mode_response}')
            else:
                send_wx_notification(f'设置单向持仓失败', f'设置单向持仓失败，错误: {change_position_mode_response}')
                logger.error(f'设置单向持仓失败，错误: {change_position_mode_response}')
        except Exception as e:
            if e.error_code == -4059:
                logger.info(f'设置单向持仓成功')
            else:
                send_wx_notification(f'设置单向持仓失败', f'设置单向持仓失败，错误: {e}')
                logger.error(f'设置单向持仓失败，错误: {e}')
        
        return jsonify({"status": "success", "message": "配置更新成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/reset_trading', methods=['GET'])
@login_required
def reset_trading():
    try:
        global trading_pairs
        trading_pairs = {}
        # 清空JSON文件
        save_trading_pairs(trading_pairs)
        logger.info('所有交易参数已重置')
        return jsonify({"status": "success", "message": "所有交易参数已重置"})
    except Exception as e:
        logger.error(f'重置交易参数失败: {str(e)}')
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':

    # 启动Flask服务
    app.run(host='0.0.0.0', port=80)
