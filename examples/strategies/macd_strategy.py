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


class MacdStrategy(CtaTemplate):
    author = "用Python的交易员"

    input_ss = 1

    poss = 0

    parameters = ["input_ss"]
    variables = ["poss"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(MacdStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager()

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
            if self.poss == 0:
                self.buy(tick.ask_price_1, self.input_ss)
            elif self.poss < 0:
                self.cover(tick.ask_price_1, self.input_ss)
                self.buy(tick.ask_price_1, self.input_ss)

        elif self.cross_below:
            self.cross_below = False
            if self.poss == 0:
                self.short(tick.bid_price_1, self.input_ss)
            elif self.poss > 0:
                self.sell(tick.bid_price_1, self.input_ss)
                self.short(tick.bid_price_1, self.input_ss)

        self.put_event()

        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """
        Callback of new bar data update.
        """

        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        macd, macdsignal, macdhist = am.macd(12, 26, 9, array=True)

        self.cross_over = macd[-1] > macdsignal[-1] and macd[-2] < macdsignal[-2]
        self.cross_below = macd[-1] < macdsignal[-1] and macd[-2] > macdsignal[-2]


    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        pass

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder):
        """
        Callback of stop order update.
        """
        pass
