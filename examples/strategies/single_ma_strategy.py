from time import sleep

from examples.util.util_wx_ft import sendWxMsg
from vnpy.app.cta_strategy import (
    CtaTemplate,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager,
)
from vnpy.app.cta_strategy.base import EngineType
from vnpy.trader.constant import Status, Offset, Direction

# LTC190927.HUOBI
# N分钟bar Ma5或dif最高点卖，最低点买


class SingleMAStrategy(CtaTemplate):
    author = "czhu"

    x_min_bar = 1  # 几分钟bar, 必须能被60整除
    ma_window = 5
    input_ss = 2

    down_count = 0
    up_count = 0

    parameters = ["x_min_bar", "ma_window", "input_ss"]
    variables = ["down_count", "up_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(SingleMAStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        if self.x_min_bar == 1:
            self.bg = BarGenerator(self.on_bar)
        else:
            self.bg = BarGenerator(self.on_bar, self.x_min_bar, self.on_x_min_bar)

        self.am = ArrayManager(40)

        self.min_range = 0.01  # 1m 经验值
        self.ma_value = 0
        self.ma_inited = False

        self.long_price = 0
        self.short_price = 0

        self.count = 0
        self.short_pos = 0
        self.long_pos = 0

        self.is_down = False
        self.is_up = False
        self.uppest = False
        self.downest = False

        self.order_time = 0
        self.entrust = 0  # 0 表示没有委托，1 表示存在开仓的委托
        self.entrust2 = 0  # -1 表示存在平仓的委托

    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")
        self.load_bar(1)

    def on_start(self):
        """
        Callback when strategy is started.
        """
        self.write_log("策略启动")
        self.put_event()

    def on_stop(self):
        """
        Callback when strategy is stopped.
        """
        self.write_log("策略停止")
        self.put_event()

    def on_tick(self, tick: TickData):
        """
        Callback of new tick data update.
        """
        if self.downest:
            self.downest = False
            if self.short_price != 0:
                if tick.ask_price_1 >= self.short_price:
                    self.write_log(f"跳过这个低点")
                elif self.short_pos >= 1:
                    self.cover(tick.ask_price_1, self.short_pos)
            if self.long_pos == 0:
                self.buy(tick.ask_price_1, self.input_ss)

        elif self.uppest:
            self.uppest = False
            if self.long_price != 0:
                if tick.bid_price_1 <= self.long_price:
                    self.write_log(f"跳过这个高点")
                elif self.long_pos >= 1:
                    self.sell(tick.bid_price_1, self.long_pos)
            if self.short_pos == 0:
                self.short(tick.bid_price_1, self.input_ss)

        self.bg.update_tick(tick)
        self.put_event()

    def on_bar(self, bar: BarData):
        if self.x_min_bar == 1:
            self.on_x_min_bar(bar)
        else:
            self.bg.update_bar(bar)

    def on_x_min_bar(self, bar: BarData):
        """
        Callback of new bar data update.
        """
        # self.count += 1
        # self.write_log("{}min_bar:{}".format(self.x_min_bar, self.count))

        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        # 首先检查是否是实盘运行还是数据预处理阶段
        if not self.inited or not self.trading:
            return

        if not self.ma_inited:
            # ma = am.sma(self.ma_window, True)
            ma, macdsignal, macdhist = am.macd(12, 26, 9, array=True)

            if ma[-1] >= ma[-2]:
                self.is_up = True
            else:
                self.is_down = True

            self.ma_inited = True
            self.ma_value = ma[-1]
            self.write_log(f"初始化完成，up:{self.is_up},down:{self.is_down}, dif:{ma[-1]}")
            return

        # new_ma_value = am.sma(self.ma_window, False)
        new_ma_value, macdsignal, macdhist = am.macd(12, 26, 9, array=False)
        # self.write_log(f"dif:{new_ma_value}")

        if self.is_up and new_ma_value >= self.ma_value or self.is_down and new_ma_value <= self.ma_value:
            self.ma_value = new_ma_value
            return

        elif self.is_up and new_ma_value < self.ma_value:  # ma最高点第一次回头，做空
            self.ma_value = new_ma_value
            self.is_up = False
            self.is_down = True
            self.uppest = True
            self.up_count += 1
            self.write_log(f'\t最高点:{self.up_count},dif:{new_ma_value}')
            if self.get_engine_type() == EngineType.LIVE:
                short_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.SHORT']))
                if short_position is not None:
                    self.short_pos = short_position.volume - short_position.frozen
                    self.write_log(u'\t空仓:{}'.format(self.short_pos))
                else:
                    self.short_pos = 0
                long_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.LONG']))
                if long_position is not None:
                    self.long_pos = long_position.volume - long_position.frozen
                    self.write_log(u'\t多仓:{}'.format(self.long_pos))
                else:
                    self.long_pos = 0

        elif self.is_down and new_ma_value > self.ma_value:  # ma最低点第一次回头，做多
            self.ma_value = new_ma_value
            self.is_up = True
            self.is_down = False
            self.downest = True
            self.down_count += 1
            self.write_log(f'\t最低点:{self.down_count},dif:{new_ma_value}')
            if self.get_engine_type() == EngineType.LIVE:
                short_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.SHORT']))
                if short_position is not None:
                    self.short_pos = short_position.volume - short_position.frozen
                    self.write_log(u'\t空仓:{}'.format(self.short_pos))
                else:
                    self.short_pos = 0
                long_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.LONG']))
                if long_position is not None:
                    self.long_pos = long_position.volume - long_position.frozen
                    self.write_log(u'\t多仓:{}'.format(self.long_pos))
                else:
                    self.long_pos = 0

        if self.entrust == 1:
            self.order_time += 1
        else:
            self.order_time = 0
        if self.x_min_bar == 1 and self.order_time > 2 or self.x_min_bar > 1 and self.order_time >= 2:   # 2分钟未完成的订单， 取消
            self.write_log("取消超时未完成的开仓单")
            self.cancel_all()
            self.order_time = 0

        self.put_event()

    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        if order.status == Status.SUBMITTING:
            if order.offset == Offset.OPEN:
                self.entrust = 1
                msg = u'{}{},{}张,价:{}'.format(order.offset.value, order.direction.value, order.volume, order.price)
                self.write_log(f'{order.status.value}{order.orderid},{msg}')
            else:
                self.entrust2 = -1
                if order.direction == Direction.LONG:
                    direc = '空'
                else:
                    direc = '多'
                msg = u'{}{},{}张,价:{}'.format(order.offset.value, direc, order.volume, order.price)
                self.write_log(f'\t{order.status.value}{order.orderid},{msg}')
        elif order.status in [Status.NOTTRADED, Status.PARTTRADED]:
            # if order.offset == Offset.OPEN:
            #     sleep(20)
            #     self.write_log("取消开单")
            #     self.cancel_all()
            #     self.entrust = 0
            pass
        elif order.status == Status.ALLTRADED:
            if order.offset == Offset.OPEN:
                self.entrust = 0
            else:
                self.entrust2 = 0
        elif order.status == Status.CANCELLED:
            self.write_log(f'\t报单更新,{order.orderid},{order.status.value}')
            if order.offset == Offset.OPEN:
                self.entrust = 0
            else:
                self.entrust2 = 0
            sleep(10)  # 10s
        elif order.status == Status.REJECTED:
            self.write_log(f'\t报单更新,{order.orderid},{order.status.value}')
            if order.offset == Offset.CLOSE:  # 平仓单异常
                self.write_log("取消多余的平仓单")
                self.cancel_all()
            if order.offset == Offset.OPEN:
                self.entrust = 0
            else:
                self.entrust2 = 0
            sleep(10)  # 10s
        else:
            self.write_log(f'\t报单更新,{order.orderid},{order.status.value}')
            pass

        self.put_event()

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        if self.entrust == 0 and trade.offset == Offset.OPEN:
            if trade.direction == Direction.LONG:
                self.long_price = trade.price
            else:
                self.short_price = trade.price

            msg = f'{trade.offset.value}{trade.direction.value},{trade.volume}张,成交价:{trade.price}'
            self.write_log(f'交易完成,{trade.orderid},{msg}')
            if self.get_engine_type() == EngineType.LIVE:
                sendWxMsg(trade.symbol + msg, '')

        if self.entrust2 == 0 and trade.offset == Offset.CLOSE:
            if trade.direction == Direction.LONG:
                direc = '空'
            else:
                direc = '多'

            msg = f'{trade.offset.value}{direc},{trade.volume}张,成交价:{trade.price}'
            self.write_log(f'\t交易完成,{trade.orderid},{msg}')
            if self.get_engine_type() == EngineType.LIVE:
                sendWxMsg(trade.symbol + msg, '')

        self.put_event()
