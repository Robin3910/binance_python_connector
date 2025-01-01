import unittest
from unittest.mock import Mock, patch
from app import GridTrader

class TestGridTrader(unittest.TestCase):
    def setUp(self):
        # 模拟 symbol_tick_size 全局变量
        self.symbol_tick_size_patcher = patch('app.symbol_tick_size', {
            'BTCUSDT': {
                'tick_size': 1,
                'min_qty': 3
            }
        })
        self.symbol_tick_size_patcher.start()
        
        # 初始化 GridTrader
        self.trader = GridTrader('BTCUSDT')
        
        # 模拟设置交易参数
        test_params = {
            'price': '30000',  # 初始价格
            'grid': '1000|1000|1000',  # 三个网格，每个大小1000
            'tp': '75',  # 止盈位置75%
            'sl': '25',  # 止损位置25%
            'qty_percent': '50'
        }
        
        # 模拟账户信息
        with patch('app.client.account') as mock_account:
            mock_account.return_value = {
                'positions': [{
                    'symbol': 'BTCUSDT',
                    'positionAmt': '1.0'
                }]
            }
            self.trader.set_trading_params(test_params)

    def tearDown(self):
        self.symbol_tick_size_patcher.stop()

    def test_update_stop_loss_grid_breakthrough(self):
        """测试价格突破网格上限的情况"""
        # 模拟下止损单
        self.trader.place_stop_loss_order = Mock()
        
        # 测试价格突破第一个网格上限
        current_price = 30510  # 高于第一个网格上限
        self.trader.update_stop_loss(current_price)
        
        # 验证结果
        self.assertTrue(self.trader.grids[0]['activated'])
        self.assertEqual(self.trader.current_grid, 0)
        self.assertEqual(self.trader.stop_loss_price, self.trader.grids[0]['tp_price'])
        self.trader.place_stop_loss_order.assert_called_once_with(self.trader.stop_loss_price)

    def test_update_stop_loss_mid_grid(self):
        """测试价格达到下一个网格50%位置的情况"""
        # 模拟下止损单
        self.trader.place_stop_loss_order = Mock()
        
        # 设置当前网格为第一个网格
        self.trader.current_grid = 0
        self.trader.grids[0]['activated'] = True
        
        # 测试价格达到第二个网格的50%位置
        current_price = 31100  # 第二个网格的中间位置
        self.trader.update_stop_loss(current_price)
        print(self.trader.stop_loss_price)
        
        # 验证结果
        self.assertEqual(self.trader.current_grid, 1)
        self.assertEqual(self.trader.stop_loss_price, self.trader.grids[1]['sl_price'])
        self.trader.place_stop_loss_order.assert_called_once_with(self.trader.stop_loss_price)

    def test_update_stop_loss_no_change(self):
        """测试价格在正常范围内不触发更新的情况"""
        # 模拟下止损单
        self.trader.place_stop_loss_order = Mock()
        
        # 测试正常价格范围
        current_price = 30100  # 在第一个网格范围内
        self.trader.update_stop_loss(current_price)
        
        # 验证结果
        self.assertFalse(self.trader.grids[0]['activated'])
        self.trader.place_stop_loss_order.assert_not_called()

if __name__ == '__main__':
    unittest.main() 