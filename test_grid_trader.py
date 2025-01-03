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
        buy_test_params = {
            'price': '30000',  # 初始价格
            'grid': '28000-32000|32000-36000|36000-40000',  # 三个网格，每个大小1000
            'grid_target': '75',  # 止盈位置75%
            'grid_tp': '25',  # 止损位置25%
            'break_tp': '75',  # 止损位置75%
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
            self.trader.set_trading_params(buy_test_params)

    def tearDown(self):
        self.symbol_tick_size_patcher.stop()

    # def test_update_stop_loss_long(self):
    #     """测试多头情况下的止损更新"""
    #     # 设置多头方向
    #     self.trader.side = "BUY"
    #     self.trader.position_qty = 1.0
        
    #     # 模拟下单函数
    #     self.trader.place_stop_loss_order = Mock()
        
    #     # 测试场景1: 价格在第一个网格的上半部分
    #     self.trader.update_stop_loss(30000)  # 在第一个网格(28000-32000)中
    #     self.assertEqual(self.trader.current_grid, 0)  # 应该在第一个网格
        
    #     # 测试场景2: 价格达到网格target位置
    #     self.trader.place_stop_loss_order.assert_called_with(self.trader.grids[0]['grid_tp'])
    #     self.assertTrue(self.trader.grids[0]['activated_target_1'])
        
    #     # 测试场景3: 价格突破网格上限
    #     self.trader.update_stop_loss(32001)  # 突破第一个网格上限
    #     self.trader.place_stop_loss_order.assert_called_with(self.trader.grids[0]['break_tp'])
    #     self.assertTrue(self.trader.grids[0]['activated_target_2'])

    # 空头的测试用例无法和多头测试用例同时运行，需要分开测试
    # 因为中间使用了binance的获取持仓数量，导致无法同时运行
    def test_update_stop_loss_short(self):
        """测试空头情况下的止损更新"""
        # 设置空头方向
        sell_test_params = {
            'price': '30000',  # 初始价格
            'grid': '28000-32000|26000-28000|24000-26000',  # 三个网格，每个大小1000
            'grid_target': '75',  # 止盈位置75%
            'grid_tp': '25',  # 止损位置25%
            'break_tp': '75',  # 止损位置75%
            'qty_percent': '50'
        }
        self.trader.set_trading_params(sell_test_params)
        self.trader.side = "SELL"
        self.trader.position_qty = -1.0
        
        # 模拟下单函数
        self.trader.place_stop_loss_order = Mock()
        
        # 测试场景1: 价格在第一个网格的下半部分
        self.trader.update_stop_loss(30000)  # 在第一个网格(28000-32000)中
        self.assertEqual(self.trader.current_grid, 0)  # 应该在第一个网格
        
        # 测试场景2: 价格达到网格target位置
        grid_target = self.trader.grids[0]['grid_target']
        self.trader.update_stop_loss(grid_target)
        self.trader.place_stop_loss_order.assert_called_with(self.trader.grids[0]['grid_tp'])
        self.assertTrue(self.trader.grids[0]['activated_target_1'])
        
        # 测试场景3: 价格突破网格下限
        self.trader.update_stop_loss(27999)  # 突破第一个网格下限
        self.trader.place_stop_loss_order.assert_called_with(self.trader.grids[0]['break_tp'])
        self.assertTrue(self.trader.grids[0]['activated_target_2'])

    # def test_update_stop_loss_multiple_grids(self):
    #     """测试跨越多个网格的情况"""
    #     self.trader.side = "BUY"
    #     self.trader.position_qty = 1.0
    #     self.trader.place_stop_loss_order = Mock()
        
    #     # 测试从第一个网格到第二个网格的转换
    #     self.trader.update_stop_loss(30000)  # 第一个网格
    #     self.assertEqual(self.trader.current_grid, 0)
        
    #     self.trader.update_stop_loss(34000)  # 第二个网格
    #     self.assertEqual(self.trader.current_grid, 1)
        
    #     # 确保之前的网格状态保持不变
    #     self.assertFalse(self.trader.grids[1]['activated_target_1'])
    #     self.assertFalse(self.trader.grids[1]['activated_target_2'])

    # def test_update_stop_loss_edge_cases(self):
    #     """测试边界情况"""
    #     self.trader.side = "BUY"
    #     self.trader.position_qty = 1.0
    #     self.trader.place_stop_loss_order = Mock()
        
    #     # 测试价格在网格边界上的情况
    #     self.trader.update_stop_loss(28000)  # 第一个网格的下边界
    #     self.assertEqual(self.trader.current_grid, 0)
        
    #     self.trader.update_stop_loss(32000)  # 第一个网格的上边界
    #     self.assertEqual(self.trader.current_grid, 0)
        
    #     # 测试价格超出所有网格范围的情况
    #     self.trader.update_stop_loss(27000)  # 低于最低网格
    #     self.trader.update_stop_loss(41000)  # 高于最高网格

if __name__ == '__main__':
    unittest.main() 