from numpy import array


def calculate_bull_bear_line(
    data: array,
    window: int = 30
):
    """计算牛熊线"""
    # 过去window周期K线的最低点
    ll = data[-window:].min()
    ll_1 = data[-window+1:-1].min()
    upll = max(ll, ll_1)

    # 过去window周期K线的最高点
    hh = data[-window:].max()
    hh_1 = data[-window+1:-1].max()
    downhh = min(hh, hh_1)

    # 比较upll和downhh计算牛熊线
    if upll <= downhh:
        bull_bear_line = upll
    else:
        bull_bear_line = downhh

    return bull_bear_line
