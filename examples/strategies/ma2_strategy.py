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
from vnpy.trader.constant import Offset, Direction, Status

# LTC190927.HUOBI
# 1分钟bar和5分钟均线金叉买， 死叉卖

class Ma2Strategy(CtaTemplate):
    author = "czhu"

    fast_window = 1
    slow_window = 5   # 慢平均线
    input_ss = 1   # 每次加仓量
    init = 10     # 初始化时间

    count_over = 0
    count_below = 0

    parameters = ["fast_window", "slow_window", "input_ss", "init"]
    variables = ["count_over", "count_below"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(Ma2Strategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(self.init)

        self.min_diff = 0.001
        self.entrust = 0
        self.count = 0

        self.short_pos = 0
        self.long_pos = 0

        self.cross_over = False
        self.cross_below = False

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
        if self.cross_over:
            self.cross_over = False
            self.buy(tick.ask_price_1, self.input_ss)
            if self.short_pos >= 1:
                self.cover(tick.ask_price_1, self.short_pos )

        elif self.cross_below:
            self.cross_below = False
            self.short(tick.bid_price_1, self.input_ss)
            if self.long_pos >= 1:
                self.sell(tick.bid_price_1, self.long_pos )

        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """
        Callback of new bar data update.
        """
        self.count += 1
        self.write_log("on_bar,{}".format(self.count))

        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        # if self.fast_window >=2:
        #     fast_ma = am.sma(self.fast_window, array=True)
        #     fast_ma0 = fast_ma[-1]
        #     fast_ma1 = fast_ma[-2]
        #
        # else:  # 1分钟bar的首尾价
        #     fast_ma0 = bar.close_price
        #     fast_ma1 = bar.open_price
        #
        # slow_ma = am.sma(self.slow_window, array=True)
        # slow_ma0 = slow_ma[-1]
        # slow_ma1 = slow_ma[-2]
        #
        # self.cross_over = fast_ma0 > slow_ma0 and fast_ma1 < slow_ma1
        # self.cross_below = fast_ma0 < slow_ma0 and fast_ma1 > slow_ma1

        macd, macdsignal, macdhist = am.macd(12, 26, 9, array=True)
        self.cross_over = macd[-1] > macdsignal[-1] and macd[-2] < macdsignal[-2]
        self.cross_below = macd[-1] < macdsignal[-1] and macd[-2] > macdsignal[-2]
        self.write_log(u'cross_over:{}, cross_below:{}'.format(self.cross_over, self.cross_below))

        if self.cross_over:
            self.count_over += 1
            self.write_log(u'cross_over,{}'.format(self.count_over))

            short_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.SHORT']))
            if short_position is not None:
                self.short_pos = short_position.volume
                self.write_log(u'    空仓:{}'.format(self.short_pos))
            else:
                self.short_pos = 0

        elif self.cross_below:
            self.count_below += 1
            self.write_log(u'cross_below,{}'.format(self.count_below))

            long_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.LONG']))
            if long_position is not None:
                self.long_pos = long_position.volume
                self.write_log(u'    多仓:{}'.format(self.long_pos))
            else:
                self.long_pos = 0

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

            self.entrust = 0

        elif order.status in [Status.CANCELLED,Status.REJECTED]:
            if order.offset == Offset.CLOSE:  # 平单异常
                self.write_log("取消多余的平仓单")
                self.cancel_all()

            sleep(5)  #10s
            self.entrust = 0

        self.put_event()

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        #self.write_log("交易完成")

        self.put_event()

    def on_stop_order(self, stop_order: StopOrder):
        """
        Callback of stop order update.
        """
        pass
