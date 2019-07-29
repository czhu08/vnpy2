from time import sleep

import numpy as np

from datetime import datetime, time
from vnpy.trader.utility import round_to

from examples.util.util_wx_ft import sendWxMsg
from vnpy.app.cta_strategy import (
    CtaTemplate,
    TickData,
    TradeData,
    BarData,
    OrderData,
    StopOrder,
)
from vnpy.trader.constant import Status, Direction, Offset

"""
入场： 每次读 Tick ，分析过去 10 个 tick 的的总计，如果买量大于卖量，开多单 ；反之空单
          下单价格是当前tick市价；
止损：下单同时开反向2个点的阻止单；
离场：下次TICK读取时候，如果已经是买入价格正向3个点，再次判断买卖量比，如果已经不符合，市价卖出；如果还是符合原来量比就极小持有，清掉之前阻止单，改挂当前价位反向2个点阻止单。

7 -24 更新，具体代码更新等验证后更新：
更改 stoporder 止损单为 limit order 限价单，这样更为快速；放在 ontrade() ，一旦主动交易确认发生后，发出这个止损 limit order
在 onorder() 加入，一旦发现发出交易没有完成，还在挂单，取消
新增一个类全局变量级别的锁，当有 order 挂单或者没有 order 发出单没有返回信息时候，这个锁关闭，不再开新单；避免多个单同时阻塞。
"""


#  LTC190802.HUOBI
#  LTC190927.HUOBI
########################################################################
class TickOneStrategy(CtaTemplate):
    """基于Tick的交易策略"""

    author = u'czhu'

    # 策略参数
    input_ss = 1
    tickSize = 30
    initDays = 0
    step = 0.4

    DAY_START = time(0, 2)  # 日盘启动和停止时间
    DAY_END = time(18, 58)
    NIGHT_START = time(19, 00)  # 夜盘启动和停止时间
    NIGHT_END = time(23, 58)

    # 策略变量
    posPrice = 0  # 持仓价格
    poss = 0  #  持仓数量

    # 参数列表，保存了参数的名称
    parameters = ['initDays',
                 'tickSize',
                 'input_ss',
                  'step'
                 ]

    # 变量列表，保存了变量的名称
    # variables = ['inited', 'trading', 'pos', 'posPrice']

    # 同步列表，保存了需要保存到数据库的变量名称
    variables = ['poss','posPrice']

    # ----------------------------------------------------------------------
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(TickOneStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        # 创建Array队列
        self.tickArray = TickArrayManager(self.tickSize)

        self.entrust = 0
        self.new_step = self.step * 0.5
        self.min_diff = 0.001
        self.wincount = 0
        
    # ----------------------------------------------------------------------
    def on_min_bar_close(self, bar):
        """"""
        # ----------------------------------------------------------------------

    def on_init(self):
        """初始化策略（必须由用户继承实现）"""
        self.write_log(u'%s策略初始化' % self.strategy_name)
        # tick级别交易，不需要过往历史数据

        #self.load_tick(0)

    # ----------------------------------------------------------------------
    def on_start(self):
        """启动策略（必须由用户继承实现）"""
        self.entrust = 0
        self.write_log(u'%s策略启动' % self.strategy_name)


    # ----------------------------------------------------------------------
    def on_stop(self):
        """停止策略（必须由用户继承实现）"""
        self.write_log(u'%s策略停止' % self.strategy_name)

    # ----------------------------------------------------------------------
    def on_tick(self, tick: TickData):
        """收到行情TICK推送（必须由用户继承实现）"""

        if self.entrust != 0:
            # if (self.__singleton2):
            #     sendWxMsg(u'委托单未全部成交',u'单号:{}'.format(ref))
            #     self.__singleton2 = False
            return

        # currentTime = datetime.now().time()
        # # 平当日仓位, 如果当前时间是结束前日盘15点28分钟,或者夜盘10点58分钟，如果有持仓，平仓。
        # if ((currentTime >= self.DAY_START and currentTime <= self.DAY_END) or
        #         (currentTime >= self.NIGHT_START and currentTime <= self.NIGHT_END)):

        if self.poss == 0:
            TA = self.tickArray
            TA.updateTick(tick)
            if not TA.inited:
                return

            # 如果空仓，分析过去10个对比，ask卖方多下空单，bid买方多下多单，并放两个差价阻止单
            if TA.askBidVolumeDif() > 0:
                price = tick.bid_price_5
                ref = self.short(price, self.input_ss, False)
                self.write_log(u'开空单{},价:{}'.format(ref, price))
                #ref = self.cover(price + self.step, self.input_ss, True)
                #self.write_log(u'平空停止单{}'.format(ref))
                self.entrust = 1
            elif TA.askBidVolumeDif() <= 0:
                price = tick.ask_price_5
                ref = self.buy(price, self.input_ss, False)
                self.write_log(u'开多单{},价:{}'.format(ref, price))
                #ref = self.sell(price - self.step, self.input_ss, True)
                #self.write_log(u'平多停止单{}'.format(ref))
                self.entrust = 1
            # re-init TA
            TA.inited = False
            TA.count = 0

        elif self.poss > 0:
            # 如果持有多单，如果已经是买入价格正向3个点，再次判断趋势，如果已经不符合，市价卖出。如果持有，清掉之前阻止单，改挂当前价位反向2个点阻止单。

            if tick.last_price - self.posPrice >= self.new_step:
                #if TA.askBidVolumeDif() < 0:
                    self.cancel_all()
                    self.wincount += 1
                    if self.wincount <= 3:
                        price = tick.last_price - self.step
                    else:
                        price = tick.last_price - self.step * 0.5
                    price = round_to(price, self.min_diff)
                    ref = self.sell(price, self.input_ss, True)
                    self.new_step += self.step * 0.5
                    self.write_log(u'  更新开多停止单{},价:{}'.format(ref, price))
                #else:
                #    self.cancel_all()
                #    ref = self.sell(tick.bid_price_1, self.input_ss, False)
                #    self.write_log(u'平多单号{},委托价：{}'.format(ref, tick.bid_price_1))
                #    self.entrust = 1

        elif self.poss < 0:
            # 如果持有空单，如果已经是买入价格反向3个点，再次判断趋势，如果已经不符合，市价卖出。如果持有，清掉之前阻止单，改挂当前价位反向2个点阻止单。
            if tick.last_price - self.posPrice <= -self.new_step:
                #if TA.askBidVolumeDif() > 0:
                    self.cancel_all()
                    self.wincount += 1
                    if self.wincount <= 3:
                        price =  tick.last_price + self.step
                    else:
                        price = tick.last_price + self.step * 0.5
                    price = round_to(price, self.min_diff)
                    ref = self.cover(price, self.input_ss, True)
                    self.new_step += self.step * 0.5
                    self.write_log(u'  更新开空停止单{},价:{}'.format(ref, price))
                #else:
                #    self.cancel_all()
                #    ref = self.cover(tick.ask_price_1, self.input_ss, False)
                #    self.write_log(u'平空单号{},委托价：{}'.format(ref, tick.ask_price_1))
                #    self.entrust = 1
        # else:
        #     if self.poss > 0:
        #         self.sell(tick.last_price, abs(self.poss), False)
        #         self.entrust = 1
        #     elif self.poss < 0:
        #         self.cover(tick.last_price, abs(self.poss), False)
        #         self.entrust = 1
        #     elif self.poss == 0:
        #         return

    # ----------------------------------------------------------------------
    def on_bar(self, bar: BarData):
        """收到Bar推送（必须由用户继承实现）"""
        pass

    # ----------------------------------------------------------------------
    def on_window_bar(self, bar):
        """收到X分钟K线"""
        pass

    # ----------------------------------------------------------------------
    def on_order(self, order: OrderData):
        """收到委托变化推送（必须由用户继承实现）"""
        '''    
        SUBMITTING = "提交中"
        NOTTRADED = "未成交"
        PARTTRADED = "部分成交"
        ALLTRADED = "全部成交"
        CANCELLED = "已撤销"
        REJECTED = "拒单"
        不完全成交会出现下面的重复bug
2019-07-28 00:01:58,261  INFO: tick1: 报单更新，19072722371710923,拒单,平,多单,价87.204
2019-07-28 00:01:58,408  INFO: tick1: 报单更新，19072722371710924,提交中,平,多单,价87.204
2019-07-28 00:01:58,785  INFO: 委托请求出错，代码：1040，信息：Invalid amount, please modify and order again.
        '''
        if order.offset == Offset.OPEN:
            msg = u'{}{},{}张,价:{}'.format(order.offset.value, order.direction.value, order.traded, order.price)
        else:
            msg = u'{},{}张,价:{}'.format(order.offset.value, order.traded, order.price)
        self.write_log(u'    报单更新,{},{},{}'.format(order.orderid,  order.status.value, msg))
        if order.status == Status.SUBMITTING:
            self.entrust = 1
        if order.status == Status.NOTTRADED:
            # if order.offset == Offset.OPEN:
            #     sleep(20)
            #     self.write_log("取消开单")
            #     self.cancel_all()
            #     self.entrust = 0
            pass
        if order.status in [Status.ALLTRADED]:
            if order.offset == Offset.OPEN:
                self.new_step = self.step * 0.5

            self.wincount = 0
            if order.direction == Direction.LONG:
                    self.poss += self.input_ss
            elif order.direction == Direction.SHORT:
                    self.poss -= self.input_ss

            self.entrust = 0
            sendWxMsg(order.symbol+msg, '')
        elif order.status in [Status.CANCELLED,Status.REJECTED]:
            if order.offset == Offset.CLOSE:  # 停止单异常
                self.write_log("取消多余的平仓单")
                self.cancel_all()

            sleep(10)  #10s
            self.entrust = 0
        else:
            pass

        self.put_event()

    # ----------------------------------------------------------------------
    def on_trade(self, trade: TradeData):
        # 同步数据到数据库
        self.posPrice = trade.price
        self.sync_data()
        if self.entrust == 0:
            msg = u'{}{},{}张,成交价:{}'.format(trade.offset.value,  trade.direction.value,  trade.volume,  trade.price)
            self.write_log(u'交易完成,{},{},pos:{}'.format(trade.orderid, msg, self.poss))

            if trade.offset == Offset.OPEN:
                if trade.direction == Direction.LONG:
                    price = trade.price - self.step
                    price = round_to(price, self.min_diff)
                    ref = self.sell(price, self.input_ss, True)
                    self.write_log(u'开多停止单{},价:{}'.format(ref, price))
                elif trade.direction == Direction.SHORT:
                    price = trade.price + self.step
                    price = round_to(price, self.min_diff)
                    ref = self.cover(price, self.input_ss, True)
                    self.write_log(u'开空停止单{},价:{}'.format(ref, price))

        self.put_event()

    # ----------------------------------------------------------------------
    def on_stop_order(self, so: StopOrder):
        """停止单推送"""
        # self.write_log(u'    停止单触发，{},价格:{}'.format(so.stop_orderid, so.price))
        # self.put_event()
        pass


########################################################################
class TickArrayManager(object):
    """
    Tick序列管理工具，负责：
    1. Tick时间序列的维护
    2. 常用技术指标的计算
    """

    # ----------------------------------------------------------------------
    def __init__(self, size=10):
        """Constructor"""
        self.count = 0  # 缓存计数
        self.size = size  # 缓存大小
        self.inited = False  # True if count>=size

        self.Ticklast_priceArray = np.zeros(self.size)
        self.TickaskVolume1Array = np.zeros(self.size)
        self.TickbidVolume1Array = np.zeros(self.size)
        self.TickaskPrice1Array = np.zeros(self.size)
        self.TickbidPrice1Array = np.zeros(self.size)
        self.TickopenInterestArray = np.zeros(self.size)
        self.TickvolumeArray = np.zeros(self.size)

    # ----------------------------------------------------------------------
    def updateTick(self, tick):
        """更新tick Array"""
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True

        self.Ticklast_priceArray[0:self.size - 1] = self.Ticklast_priceArray[1:self.size]
        self.TickaskVolume1Array[0:self.size - 1] = self.TickaskVolume1Array[1:self.size]
        self.TickbidVolume1Array[0:self.size - 1] = self.TickbidVolume1Array[1:self.size]
        self.TickaskPrice1Array[0:self.size - 1] = self.TickaskPrice1Array[1:self.size]
        self.TickbidPrice1Array[0:self.size - 1] = self.TickbidPrice1Array[1:self.size]
        self.TickopenInterestArray[0:self.size - 1] = self.TickopenInterestArray[1:self.size]
        self.TickvolumeArray[0:self.size - 1] = self.TickvolumeArray[1:self.size]

        self.Ticklast_priceArray[-1] = tick.last_price
        self.TickaskVolume1Array[-1] = tick.ask_volume_1
        self.TickbidVolume1Array[-1] = tick.bid_volume_1
        self.TickaskPrice1Array[-1] = tick.ask_price_1
        self.TickbidPrice1Array[-1] = tick.bid_price_1
        self.TickopenInterestArray[-1] = tick.open_interest
        self.TickvolumeArray[-1] = tick.volume

    def askBidVolumeDif(self):
        return (self.TickaskVolume1Array.sum() - self.TickbidVolume1Array.sum())