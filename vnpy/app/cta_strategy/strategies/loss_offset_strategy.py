from vnpy.trader.utility import round_to

from vnpy.app.cta_strategy import (
    CtaTemplate,
    TickData,
    TradeData,
    OrderData,
)
from vnpy.trader.constant import Status, Direction, Offset

"""
亏损补偿策略
如果到达止盈价，平多
如果到达止损价，开空，到空单和多单的中间价时全部平仓
"""
class LossOffsetStrategy(CtaTemplate):
    """"""

    author = "czhu"

    # this is LTC example
    min_diff = 0.01
    input_ss = 1
    offset = 1
    quote = "LTC"

    long_price = 0.0
    short_price = 0.0

    entrust = 0

    parameters = ["quote", "min_diff", "input_ss", "offset"]
    variables = ["long_price","short_price"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(LossOffsetStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")

    def on_start(self):
        """
        Callback when strategy is started.
        """
        long_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.LONG']))
        if long_position is not None:
            self.long_price = long_position.price

        short_position = self.cta_engine.main_engine.get_position('.'.join([self.vt_symbol, 'Direction.SHORT']))
        if short_position is not None:
            self.short_price = short_position.price

        self.write_log("策略启动")

    def on_stop(self):
        """
        Callback when strategy is stopped.
        """
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        """
        Callback of new tick data update. run once one second
        """
        # 首先检查是否是实盘运行还是数据预处理阶段
        if not self.inited or not self.trading:
            return

        if self.entrust != 0:
            return

        if self.long_price == 0:
            # 如果没有多单，开多单
            price = tick.ask_price_1  #卖一价
            price = round_to(price, self.min_diff)
            ref = self.buy(price=price, volume=self.input_ss)
            if ref is not None and len(ref) > 0:
                self.entrust = 1
                self.write_log(u'开多委托单号{},委托买入价：{}'.format(ref, price))
            else:
                self.write_log(u'开多委托单失败:价格:{},数量:{}'.format(price, self.input_ss))
        elif tick.last_price >= (self.long_price * (1 + self.offset/100)):
            # 平多
            price = tick.bid_price_1  #买一价
            price = round_to(price, self.min_diff)
            ref = self.sell(price, self.input_ss)
            if ref is not None and len(ref) > 0:
                self.entrust = 2
                self.write_log(u'平多委托单号{},委托卖出价：{}'.format(ref, price))
            else:
                self.write_log(u'平多委托单失败:价格:{},数量:{}'.format(price, self.input_ss))
        elif tick.last_price <= (self.long_price * (1 - self.offset/100)) and self.short_price == 0:
            # 开空，对冲亏损
            price = tick.bid_price_1  #买一价
            price = round_to(price, self.min_diff)
            ref = self.short(price, self.input_ss)
            if ref is not None and len(ref) > 0:
                self.entrust = -1
                self.write_log(u'开空委托单号{},委托卖出价：{}'.format(ref, price))
            else:
                self.write_log(u'开空委托单失败:价格:{},数量:{}'.format(price, self.input_ss))
        elif tick.last_price == ((self.long_price + self.short_price) / 2) and self.short_price > 0:
            # 清仓
            price = tick.ask_price_1
            price = round_to(price, self.min_diff)
            ref = self.cover(price, self.input_ss)
            if ref is not None and len(ref) > 0:
                self.entrust = -2
                self.write_log(u'平空委托单号{},委托卖出价：{}'.format(ref, price))
            else:
                self.write_log(u'平空委托单失败:价格:{},数量:{}'.format(price, self.input_ss))

            ref = self.sell(price, self.input_ss)
            if ref is not None and len(ref) > 0:
                self.entrust = 2
                self.write_log(u'平多委托单号{},委托卖出价：{}'.format(ref, price))
            else:
                self.write_log(u'平多委托单失败:价格:{},数量:{}'.format(price, self.input_ss))

    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        msg = u'报单更新,委托编号:{},合约:{},方向:{},价格:{},委托:{},成交:{},状态:{}'.format(order.orderid, order.symbol,
                                 order.direction, order.price,
                                 order.volume,order.traded,
                                 order.status)

        self.write_log(msg)

        if order.volume == order.traded or order.status == Status.ALLTRADED:
            # 开仓，平仓委托单全部成交
            # 计算收益
            if order.direction == Direction.LONG:
                if order.offset == Offset.OPEN:
                    # 开多
                    self.long_price = order.price
                else:
                    # 平空
                    self.short_price = 0
            else:
                if order.offset == Offset.OPEN:
                    # 开空
                    self.short_price = order.price
                else:
                    # 平多
                    self.long_price = 0

            self.entrust = 0
        elif order.status in [Status.CANCELLED,Status.REJECTED]:
            self.entrust = 0
        self.put_event()

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.put_event()