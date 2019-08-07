from time import sleep

from examples.util.util_wx_ft import sendWxMsg
from vnpy.app.cta_strategy import (
    CtaTemplate,
    StopOrder,
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
# N分钟bar RSI低于20买，高于80卖

class RSIStrategy(CtaTemplate):
    author = "czhu"

    x_min_bar = 1 # 几分钟bar, 必须能被60整除
    rsi_length = 6
    input_ss = 1

    down_line = 30
    up_line = 70

    down_count = 0
    up_count = 0


    parameters = ["x_min_bar", "rsi_length", "input_ss", "down_line", "up_line"]
    variables = ["down_count", "up_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(RSIStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        if self.x_min_bar == 1:
            self.bg = BarGenerator(self.on_bar)
        else:
            self.bg = BarGenerator(self.on_bar, self.x_min_bar, self.on_window_bar)

        self.am = ArrayManager(40)

        self.min_range = 0.01  # 1m 经验值
        self.rsi_value = 0

        self.count = 0
        self.short_pos = 0
        self.long_pos = 0
        self.uppest = False
        self.downest = False
        self.order_time = 0
        self.entrust = 0

    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")
        self.load_bar(30)

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
            if self.long_pos == 0:
                self.buy(tick.ask_price_1, self.input_ss)
            if self.short_pos >= 1:
                self.cover(tick.ask_price_1, self.short_pos)

        elif self.uppest:
            self.uppest = False
            if self.short_pos == 0:
                self.short(tick.bid_price_1, self.input_ss)
            if self.long_pos >= 1:
                self.sell(tick.bid_price_1, self.long_pos)

        self.bg.update_tick(tick)
        self.put_event()

    def on_bar(self, bar : BarData):
        if self.x_min_bar == 1:
            self.on_x_min_bar(bar)
        else:
            self.bg.update_bar(bar)

    def on_window_bar(self, bar: BarData):
        self.on_x_min_bar(bar)

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

        new_rsi_value = am.rsi(self.rsi_length)
        if new_rsi_value > self.down_line and new_rsi_value < self.up_line:
            self.rsi_value = new_rsi_value
            return

        elif new_rsi_value <= self.down_line:
            if new_rsi_value <= self.rsi_value:
                self.rsi_value = new_rsi_value
                return
            else:  #rsi最低点第一次回头，做多
                self.downest = True
                self.down_count += 1
                self.write_log(u'    RSI过低:{}'.format(new_rsi_value))
                if self.get_engine_type() == EngineType.LIVE:
                    short_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.SHORT']))
                    if short_position is not None:
                        self.short_pos = short_position.volume - short_position.frozen
                        self.write_log(u'    空仓:{}'.format(self.short_pos))
                    else:
                        self.short_pos = 0
                    long_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.LONG']))
                    if long_position is not None:
                        self.long_pos = long_position.volume - long_position.frozen
                        self.write_log(u'    多仓:{}'.format(self.long_pos))
                    else:
                        self.long_pos = 0
                else: #回测
                    self.buy(bar.close_price, self.input_ss)
                    self.cover(bar.close_price, self.input_ss)


        else: # new_rsi_value >= self.up_line:
            if new_rsi_value >= self.rsi_value:
                self.rsi_value = new_rsi_value
                return
            else:  #rsi最高点第一次回头，做空
                self.uppest = True
                self.up_count += 1
                self.write_log(u'    RSI过高:{}'.format(new_rsi_value))
                if self.get_engine_type() == EngineType.LIVE:
                    short_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.SHORT']))
                    if short_position is not None:
                        self.short_pos = short_position.volume - short_position.frozen
                        self.write_log(u'    空仓:{}'.format(self.short_pos))
                    else:
                        self.short_pos = 0
                    long_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.LONG']))
                    if long_position is not None:
                        self.long_pos = long_position.volume - long_position.frozen
                        self.write_log(u'    多仓:{}'.format(self.long_pos))
                    else:
                        self.long_pos = 0
                else: #回测
                    self.short(bar.close_price, self.input_ss)
                    self.sell(bar.close_price, self.input_ss)


        if self.entrust == 1:
            self.order_time +=1
        else:
            self.order_time = 0
        if self.x_min_bar == 1 and self.order_time > 2 or self.x_min_bar >1 and self.order_time >= 1:   # 2分钟未完成的订单， 取消
            self.write_log("取消超时未完成的订单")
            self.cancel_all()
            self.order_time = 0

        self.put_event()

    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        if order.status == Status.SUBMITTING:
            self.entrust = 1
            if order.offset == Offset.OPEN:
                msg = u'{}{},{}张,价:{}'.format(order.offset.value, order.direction.value, order.volume, order.price)
            else:
                if order.direction == Direction.LONG:
                    dir = '空'
                else:
                    dir = '多'
                msg = u'{}{},{}张,价:{}'.format(order.offset.value, dir, order.volume, order.price)

            self.write_log(u'    报单更新,{},{},{}'.format(order.orderid, order.status.value, msg))
        elif order.status in [Status.ALLTRADED]:
            self.entrust = 0
            if order.offset == Offset.OPEN:
                msg = u'{}{},{}张,价:{}'.format(order.offset.value, order.direction.value, order.volume, order.price)
            else:
                if order.direction == Direction.LONG:
                    dir = '空'
                else:
                    dir = '多'
                msg = u'{}{},{}张,价:{}'.format(order.offset.value, dir, order.volume, order.price)

            self.write_log(u'    报单更新,{},{},{}'.format(order.orderid, order.status.value, msg))

            if self.get_engine_type() == EngineType.LIVE:
                sendWxMsg(order.symbol + msg, '')


        elif order.status in [Status.CANCELLED,Status.REJECTED]:
            if order.offset == Offset.CLOSE:  # 平单异常
                self.write_log("取消多余的平仓单")
                self.cancel_all()
            self.entrust = 0
            sleep(5)  #10s


    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.sync_data()
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder):
        """
        Callback of stop order update.
        """
        pass
