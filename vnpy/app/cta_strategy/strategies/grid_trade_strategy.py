from vnpy.app.cta_strategy import (
    CtaTemplate,
    TickData,
    TradeData,
    OrderData,
)
from vnpy.trader.constant import Status
from vnpy.trader.util_wx_ft import sendWxMsg

"""
币币交易区间网格策略
上涨height就平，下跌height就开，高抛低吸
"""
class GridTradeStrategy(CtaTemplate):
    """"""

    author = "jasion"

    # this is LTC example
    min_diff = 0.01
    input_ss = 0.1
    grid_up_line = 150
    grid_mid_line = 130
    grid_dn_line = 120
    grid_height = 4
    quote = "usdt"

    base_line = 0
    new_up = 0
    new_down = 0
    entrust = 0
    base = ""

    parameters = ["quote", "min_diff", "input_ss", "grid_up_line",
                  "grid_mid_line", "grid_dn_line", "grid_height"]
    variables = ["base_line"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(GridTradeStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        if self.base_line == 0:
            self.base_line = self.grid_mid_line
            self.new_up = self.base_line * (1 + self.grid_height / 100)
            self.new_down = self.base_line / (1 + self.grid_height / 100)

        dict = self.vt_symbol.partition(self.quote)  #vt_symbol = ltcusdt.HUOBI
        self.base = dict[0]

    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")

    def on_start(self):
        """
        Callback when strategy is started.
        """
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

        if tick.last_price > self.grid_up_line or tick.last_price < self.grid_dn_line or self.entrust != 0:
        #    self.write_log("price out grid")
            return

        # 下限清仓
        if tick.last_price <= self.grid_dn_line + self.min_diff:
            base_pos = self.cta_engine.main_engine.get_account('.'.join([tick.exchange.value, self.base]))
            sell_volume = base_pos.balance
            if sell_volume >= self.min_diff:
                price = tick.bid_price_1  # 买一价
                ref = self.sell(price=price, volume=sell_volume)
                if ref is not None and len(ref) > 0:
                    self.entrust = -1
                    self.write_log(u'清仓委托卖出成功, 委托编号:{},委托价格:{}卖出数量{}'.format(ref, price, sell_volume))
                    sendWxMsg(u'清仓委托卖出成功' ,u'委托编号:{},委托价格:{}卖出数量{}'.format(ref, price, sell_volume) )
                else:
                    self.write_log(u'清仓委托卖出{}失败,价格:{},数量:{}'.format(self.vt_symbol, price, sell_volume))


        #if base_pos is None or account is None:
        #    self.write_log(u'获取不到持仓')
        #    return

        price= tick.last_price

        if price <= self.new_down:
            # 买入
            account = self.cta_engine.main_engine.get_account('.'.join([tick.exchange.value, self.quote]))
            price = tick.ask_price_1  #卖一价
            buy_volume = min(account.balance/price, float(self.input_ss))
            if buy_volume < self.min_diff:
                return

            ref = self.buy(price=price, volume=self.input_ss)
            if ref is not None and len(ref) > 0:
                self.entrust = 1
                self.write_log(u'开多委托单号{},委托买入价：{}'.format(ref, price))
            else:
                self.write_log(u'开多委托单失败:价格:{},数量:{}'.format(price, self.input_ss))

        elif price >= self.new_up:
            # 卖出
            base_pos = self.cta_engine.main_engine.get_account('.'.join([tick.exchange.value, self.base]))
            price = tick.bid_price_1  #买一价
            sell_volume = min(base_pos.balance, float(self.input_ss))
            if sell_volume < self.min_diff:
                return
            ref = self.sell(price=price, volume=sell_volume)
            if ref is not None and len(ref) > 0:
                self.entrust = -1
                self.write_log(u'委托卖出成功, 委托编号:{},委托价格:{}卖出数量{}'.format(ref, price, sell_volume))
            else:
                self.write_log(u'委托卖出{}失败,价格:{},数量:{}'.format(self.vt_symbol, price, sell_volume))


    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        msg = u'报单更新,委托编号:{},合约:{},方向:{},价格:{},委托数量:{},成交:{},状态:{}'.format(order.orderid, order.symbol,
                                 order.direction, order.price,
                                 order.volume,order.traded,
                                 order.status)
        sub = u'{}, {}'.format(order.direction, order.price)

        self.write_log(msg)

        if order.volume == order.traded or order.status == Status.ALLTRADED:
            # 开仓，平仓委托单全部成交
            self.base_line = order.price
            self.new_up = self.base_line * (1 + self.grid_height / 100)
            self.new_down = self.base_line / (1 + self.grid_height / 100)
            self.entrust = 0
            #self.send_email(msg)
            sendWxMsg(sub, msg)
        elif order.status in [Status.CANCELLED,Status.REJECTED]:
            self.entrust = 0
        self.put_event()

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.put_event()