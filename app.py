# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
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

app = Flask(__name__)

# 配置信息
WX_TOKEN = WX_CONFIG['token']

ip_white_list = BINANCE_CONFIG['ip_white_list']

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
        requests.get(f'https://wx.xtuis.cn/{WX_TOKEN}.send?text={title}&desp={message}')
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
    logger.error(
        "Found error. status: {}, error code: {}, error message: {}".format(
            error.status_code, error.error_code, error.error_message
        )
    )

# 创建全局字典来存储不同币种的交易信息
trading_pairs = {}

class GridTrader:
    def __init__(self, symbol):
        self.symbol = prefix_symbol(symbol)
        self.current_grid = 0
        self.grids = []
        self.stop_loss_price = 0
        self.position_qty = 0
        self.initial_price = 0
        self.is_monitoring = False  # 添加监控状态标志
        self.monitor_thread = None  # 添加监控线程对象
        self.stop_loss_order_id = None  # 添加止损单ID
        self.side = ""
        
        logger.info(f'{symbol} GridTrader 初始化完成')
        
    def set_trading_params(self, data):
        logger.info(f'设置交易参数: {json.dumps(data, ensure_ascii=False)}')
        self.initial_price = float(data['price'])  # 当前价格
        
        # 解析新的网格格式
        grid_ranges = [x.split('-') for x in data['grid'].split('|')]
        
        # 构建网格
        self.grids = []
        for lower_str, upper_str in grid_ranges:
            lower = float(lower_str)
            upper = float(upper_str)
            size = upper - lower
            
            self.grids.append({
                'lower': round(lower, symbol_tick_size[self.symbol]['tick_size']),
                'upper': round(upper, symbol_tick_size[self.symbol]['tick_size']),
                'tp_price': round(lower + (size * float(data['tp'])/100), symbol_tick_size[self.symbol]['tick_size']),
                'sl_price': round(lower + (size * float(data['sl'])/100), symbol_tick_size[self.symbol]['tick_size']),
                'activated': False,
                'size': size
            })
        
        # TODO 把止损单通过接口捞出来，如果没有止损单，则以当前网格的下线作为止损，挂个止损单

        # 设置初始止损价格
        self.stop_loss_price = round(self.grids[0]['sl_price'], symbol_tick_size[self.symbol]['tick_size'])
        # 获取持仓数量
        try:
            response = client.account(recvWindow=6000)
            for item in response['positions']:
                if item['symbol'] == self.symbol:
                    self.position_qty = round(float(item['positionAmt']) * float(data['qty_percent'])/100, symbol_tick_size[self.symbol]['min_qty'])
                    self.side = "BUY" if float(item['positionAmt']) > 0 else "SELL"
                    if self.side == "SELL":
                        self.position_qty = -self.position_qty
                    break
        except ClientError as error:
            logger.error(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.error_code, error.error_message
                )
            )

        logger.info(f'网格设置完成，初始止损价格: {self.stop_loss_price}')

    def place_stop_loss_order(self, price):
        """下止损单"""
        logger.info(f'下止损单，价格: {price}, 数量: {self.position_qty}')
        if self.stop_loss_order_id:
            logger.info(f'止损单已存在，先撤销，ID: {self.stop_loss_order_id}')
            # 撤销之前的止损单
            client.cancel_order(symbol=self.symbol, orderId=self.stop_loss_order_id,recvWindow=2000)
        # 调用Binance API下止损单
        # 记录止损单ID
        try:
            response = client.new_order(
                symbol=self.symbol,
                side="SELL" if self.side == "BUY" else "BUY",
                type="STOP",
                quantity=self.position_qty,
                timeInForce="GTC",
                price=price,
                stopPrice=price,
            )
            logger.info(response)
            if response['orderId'] is not None:
                self.stop_loss_order_id = response['orderId']
                logger.info(f'止损单已创建，ID: {self.stop_loss_order_id}')
                send_wx_notification(f'{self.symbol} 止损单已创建', f'止损单已创建，ID: {self.stop_loss_order_id}')
            else:
                logger.error(f'止损单创建失败，响应: {response}')
                send_wx_notification(f'{self.symbol} 止损单创建失败', f'止损单创建失败，响应: {response}')

        except ClientError as error:
            logger.error(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.error_code, error.error_message
                )
            )

    def update_stop_loss(self, current_price):
        """更新止损价格"""
        # logger.info(f'核查是否要更新止损价格，{self.symbol}当前价格: {current_price}')
        
        for i, grid in enumerate(self.grids):
            if current_price > grid['tp_price'] and not grid['activated']:
                grid['activated'] = True
                # 更新止损价格为止盈价格
                self.stop_loss_price = grid['sl_price']
                self.current_grid = i
                self.place_stop_loss_order(self.stop_loss_price)
                logger.info(f'价格来到网格{i+1}的上半部分，设置止盈价格: {self.stop_loss_price}')
                send_wx_notification(f'{self.symbol}|网格{i+1}上移止损', f'价格来到网格{i+1}的上半部分，设置止盈价格: {self.stop_loss_price}')
                break
            # 当价格突破网格上限时
            if current_price > grid['upper'] and not grid['activated']:
                grid['activated'] = True
                # 设置止盈价格为当前网格大小的tp%位置
                tp_price = grid['tp_price']
                # 更新止损价格为止盈价格
                self.stop_loss_price = tp_price
                self.current_grid = i
                self.place_stop_loss_order(self.stop_loss_price)
                logger.info(f'价格突破网格{i+1}上限，设置止盈价格: {tp_price}')
                send_wx_notification(f'{self.symbol} 价格突破网格{i+1}上限', f'价格突破网格{i+1}上限，设置止损价格: {tp_price}')
                break
            # 如果价格上升到了下一个网格的50%，则上移止损价格到下一个网格的下线
            elif current_price > grid['lower'] + 0.5 * grid['size'] and not grid['activated'] and self.current_grid == i - 1:
                self.stop_loss_price = grid['sl_price'] # 下一个网格的25%位置
                self.current_grid = i
                self.place_stop_loss_order(self.stop_loss_price)
                logger.info(f'价格上升到网格{i}的50%，上移止损价格到网格{i+1}的下限: {self.stop_loss_price}')
                send_wx_notification(f'{self.symbol} 价格上升到网格{i}的50%', f'价格上升到网格{i}的50%，上移止损价格到网格{i+1}的下限: {self.stop_loss_price}')
                break

    def monitor_price(self):
        """监控价格并更新止损"""
        self.is_monitoring = True
        logger.info(f'{self.symbol} 开始价格监控')
        
        while self.is_monitoring:
            try:
                # 检查止损单状态
                if self.stop_loss_order_id:
                    try:
                        order_status = client.query_order(
                            symbol=self.symbol,
                            orderId=self.stop_loss_order_id
                        )
                        # 如果止损单已执行完成，停止监控
                        if order_status['status'] == 'CANCELED' or order_status['status'] == 'FILLED':
                            logger.info(f'{self.symbol} 止损单已执行，停止监控')
                            send_wx_notification(f'{self.symbol} 止损单已执行', f'止损单已执行，停止监控')
                            self.stop_monitoring()
                            break
                    except Exception as e:
                        logger.error(f'查询止损单状态失败: {str(e)}')
                # 获取当前价格
                current_price = float(client.mark_price(self.symbol)['markPrice'])
                
                # 更新止损价格
                self.update_stop_loss(current_price)
                
                time.sleep(2)  # 每2秒检查一次
            except Exception as e:
                logger.error(f'{self.symbol} 监控价格时发生错误: {str(e)}')
                time.sleep(2)  # 发生错误时也等待2秒
                
    def stop_monitoring(self):
        """停止价格监控"""
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
            logger.info(f'{self.symbol} 停止价格监控')

# {
#   "symbol": "BTCUSDT", // 币种
# 	"qty_percent": 50, // 用于决定平仓数量。比如我手上有1000USDT的BTC，
#                       50代表我只要有50%的仓位用于该平仓的逻辑。剩下的50%不要去动它
# 	"price": 100000, // 当前的价格
# 	"grid": "96000-97000|97000-98000|98000-99000", // 代表网格的大小。第一个网格则为[96000,97000]，第二个网格为[97000,98000]，
#                               第三个网格为[98000,99000]，最多为三个网格
# 	"sl": 20, // 代表当价格下跌的20%的时候，就平仓。
# 	"tp": 75, // 当价格冲破第一个网格的上线时，即101000，设置一个出场点在第一个网格的75%的位置，
#                如果价格下跌到第一个网格的75%则平仓止盈。如果价格还是不断上升，达到第二个网格的50%，则启动第二个网格的逻辑。
#                第二个网格的止盈止损逻辑与第一个网格是类似的。同理，第三个网格的逻辑也和第二个网格的逻辑一致。
# }
# 
@app.route('/message', methods=['POST'])
def handle_message():
    try:
        data = request.get_json()
        symbol = data['symbol']
        logger.info(f'收到 {symbol} 的新交易参数请求: {json.dumps(data, ensure_ascii=False)}')
        
        # 检查该币种是否已在监控中
        if symbol in trading_pairs and trading_pairs[symbol].is_monitoring:
            logger.warning(f'{symbol} 已经处于监控状态')
            return jsonify({
                "status": "error", 
                "message": f"{symbol} 已经处于监控状态，请先停止现有监控后再重新设置"
            })
        
        # 如果该币种已存在但未在监控中，先停止之前的监控线程
        if symbol in trading_pairs:
            trading_pairs[symbol].stop_monitoring()
        
        # 创建或更新 GridTrader 实例
        trading_pairs[symbol] = GridTrader(symbol)
        
        # 设置交易参数
        trading_pairs[symbol].set_trading_params(data)
        
        # 立即设置初始止损单
        # 将挂止损单的操作上移到set_trading_params中
        # trading_pairs[symbol].place_stop_loss_order(trading_pairs[symbol].stop_loss_price)
        
        # 启动价格监控线程
        trading_pairs[symbol].monitor_thread = threading.Thread(
            target=trading_pairs[symbol].monitor_price
        )
        trading_pairs[symbol].monitor_thread.daemon = True
        trading_pairs[symbol].monitor_thread.start()
        
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
    logger.info(request.json)
    if request.json is None:
        return jsonify({'error': '请求体不能为空'}), 400
    if request.remote_addr not in ip_white_list:
        logger.info(f'ipWhiteList: {ip_white_list}')
        logger.info(f'ip is not in ipWhiteList: {request.remote_addr}')
        return jsonify({'error': 'ip is not in ipWhiteList'}), 403


if __name__ == '__main__':
    # 启动定时发送消息的线程
    message_thread = threading.Thread(target=send_wx_message)
    message_thread.daemon = True
    message_thread.start()
    
    # 启动Flask服务
    app.run(host='0.0.0.0', port=80)
